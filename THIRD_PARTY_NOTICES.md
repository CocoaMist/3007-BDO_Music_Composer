# Third-party notices

This project depends on third-party software, including PySide6/Qt, Mido, NumPy, and PyInstaller. Their respective licenses and notices apply; see the dependency metadata installed with each package and the official upstream projects.

The root MIT License applies only to original BDO Music Composer code owned by CocoaMist. It does not relicense third-party components.

## Optional CC0 sample-pack release asset

`BDO-Approximate-CC0-Full-Coverage-v4-Compact.bdosamples` may be published
beside the Windows application as a separate, optional preview asset. It is not
part of the repository or embedded in `BDO-Music-Composer.exe`. The v4 pack
selects unmodified WAV bytes from the following independently published CC0
sources:

- [VSCO 2 Community Edition](https://github.com/sgossner/VSCO-2-CE), source
  revision `6dd651d55dde97fd4028699be9d4481f26917891`.
- [Versilian Community Sample Library](https://github.com/sgossner/VCSL),
  source revision `c1ea7bcc3c7309650ab0da9d15c9cd1fbc4a4c7e`.
- [FreePats](https://freepats.zenvoid.org/) CC0 Spanish classical guitar,
  clean electric guitar, picked bass, concert harp, and clarinet banks.

CC0 1.0 terms are available from
[Creative Commons](https://creativecommons.org/publicdomain/zero/1.0/legalcode.en).
The pack's `manifest.json` records the source library, upstream relative path,
and SHA-256 for every audio slot so the assembled asset remains auditable.
The pack contains no Black Desert client audio. It provides approximate editor
preview only and must not be described as game-original or A/B-verified sound.
Its inclusion does not alter the client-content boundary in
[`docs/CONTENT_BOUNDARY.md`](docs/CONTENT_BOUNDARY.md).

## Human-readable upstream credits

This table records the direct and release-relevant foundations of the current
application. Every entry links to its GitHub source. It complements, rather
than replaces, the exact transitive inventory embedded in each Windows build.

| Project | Role | License / terms | GitHub |
|---|---|---|---|
| Spotify Basic Pitch 0.4.0 + `nmp.onnx` | Automatic music transcription | Apache-2.0 | [spotify/basic-pitch](https://github.com/spotify/basic-pitch) |
| Microsoft ONNX Runtime | Basic Pitch ONNX CPU inference | MIT | [microsoft/onnxruntime](https://github.com/microsoft/onnxruntime) |
| librosa | Audio/music analysis | ISC | [librosa/librosa](https://github.com/librosa/librosa) |
| SoundFile | Python audio-file I/O | BSD-3-Clause | [bastibe/python-soundfile](https://github.com/bastibe/python-soundfile) |
| libsndfile | Native audio-file I/O shipped by SoundFile wheels | LGPL-2.1-or-later | [libsndfile/libsndfile](https://github.com/libsndfile/libsndfile) |
| python-soxr | Python resampling binding | LGPL-2.1-or-later | [dofuuz/python-soxr](https://github.com/dofuuz/python-soxr) |
| libsoxr | Native SoX resampler | LGPL-2.1-or-later | [chirlu/soxr](https://github.com/chirlu/soxr) |
| NumPy | Array/audio computation | BSD-3-Clause plus bundled notices | [numpy/numpy](https://github.com/numpy/numpy) |
| SciPy | Scientific computation | BSD-3-Clause plus bundled notices | [scipy/scipy](https://github.com/scipy/scipy) |
| scikit-learn | Basic Pitch scientific stack | BSD-3-Clause | [scikit-learn/scikit-learn](https://github.com/scikit-learn/scikit-learn) |
| Numba | JIT acceleration used by the audio stack | BSD-2-Clause | [numba/numba](https://github.com/numba/numba) |
| llvmlite | LLVM binding used by Numba | BSD-2-Clause and Apache-2.0 WITH LLVM-exception | [numba/llvmlite](https://github.com/numba/llvmlite) |
| mir_eval | Music-information-retrieval evaluation | MIT | [mir-evaluation/mir_eval](https://github.com/mir-evaluation/mir_eval) |
| pretty_midi | MIDI representation used by Basic Pitch | MIT | [craffel/pretty-midi](https://github.com/craffel/pretty-midi) |
| resampy | Audio resampling dependency | ISC | [bmcfee/resampy](https://github.com/bmcfee/resampy) |
| CPython | Python runtime | PSF-2.0 | [python/cpython](https://github.com/python/cpython) |
| PySide6 / Qt | Desktop UI and multimedia runtime | LGPL-3.0/GPL, module-specific | [Qt official GitHub mirror](https://github.com/qt) |
| Mido | Standard MIDI parsing and writing | MIT | [mido/mido](https://github.com/mido/mido) |
| Pillow | Build-time image/icon processing | MIT-CMU | [python-pillow/Pillow](https://github.com/python-pillow/Pillow) |
| PyInstaller | Windows one-file packaging | GPL-2.0-or-later with special exception | [pyinstaller/pyinstaller](https://github.com/pyinstaller/pyinstaller) |
| Setuptools | Package metadata/build support | MIT | [pypa/setuptools](https://github.com/pypa/setuptools) |
| typing_extensions | Python typing compatibility | PSF-2.0 | [python/typing_extensions](https://github.com/python/typing_extensions) |

License labels above are human-readable summaries of the installed metadata.
Bundled subcomponents retain their own notices and may make a package's exact
license expression broader than the short label.

## Basic Pitch code and ONNX model

The official Basic Pitch v0.4.0 release places its
[`LICENSE`](https://github.com/spotify/basic-pitch/blob/v0.4.0/LICENSE),
[`NOTICE`](https://github.com/spotify/basic-pitch/blob/v0.4.0/NOTICE), and
packaged
[`nmp.onnx`](https://github.com/spotify/basic-pitch/blob/v0.4.0/basic_pitch/saved_models/icassp_2022/nmp.onnx)
in the same tagged repository tree. The installed wheel likewise contains the
model and both notice files. No separate restrictive model license was found.
The unmodified model is therefore treated as part of the Apache-2.0 Basic
Pitch distribution; redistribution must include the license and retain the
applicable NOTICE material. The evidence and remaining release boundary are
documented in
[`docs/BASIC_PITCH_LICENSE_REVIEW.md`](docs/BASIC_PITCH_LICENSE_REVIEW.md).

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
and their transitive dependencies listed by `requirements/transcription.txt`.
Source checkouts install the same runtime through
`scripts/install_transcription.ps1`. These packages retain their own upstream
terms and notices.

The Basic Pitch model finding resolves that model's upstream licensing
evidence. For v1.0.0, the deterministic schema-2 scientific Python/native
dependency inventory and its available notice files were reviewed and approved
in the checked-in public-release policy. A different dependency inventory
remains blocked until it receives a new review.

The semantic-block, harmony, deterministic voice-grouping, and BDO Top-3
features do not add another pretrained model or a separate product edition.
They operate within the existing Basic Pitch/scientific dependency set already
covered by the generated build inventory. References to Sonic Visualiser, Tony,
Chordino, MT3, YourMT3, Essentia, and Omnizart describe interaction or research
context only; no source code, model, or runtime from those projects is copied or
bundled by this implementation.

Historical/reference acknowledgements also link to their GitHub origin:

- [iDevelopThings / bdo-data-extractor](https://github.com/iDevelopThings/bdo-data-extractor)
  is retained as a historical format-research reference; its code and a
  general extraction workflow are not bundled by the application.
- [Bishop-R](https://github.com/Bishop-R) and
  [Skyro468](https://github.com/Skyro468) are credited for historical public
  BDO-format research; their runtime code is not present in v0.3.0.
- [OpenAI](https://github.com/openai) is acknowledged for development
  collaboration. The application contains no OpenAI API or cloud-model runtime.

The development-only transcription benchmark can download BabySlakh from
Zenodo record 4603844. BabySlakh is licensed CC BY 4.0. Its audio and MIDI are
stored only in the user's local benchmark cache and are not committed,
packaged, or redistributed with this application.

Optional timbre matching reads only compatible samples that the user selects
locally and has independently obtained the right to use. The application does
not acquire or distribute those samples. Its Local AppData
cache contains content-keyed aggregate feature profiles, not WAV payloads,
audio clips, sample paths, or reference-audio paths; neither that cache nor the
reference audio is included in project files or the Windows executable.

Every `BDO-Music-Composer.exe` build runs
`scripts/audit_transcription_licenses.py`. It records the installed transitive
dependency graph, versions, declared licenses, available license files, and
hashes of the ONNX model and ONNX Runtime native libraries. Available notice
files and the generated report are embedded in the executable. The checked-in
`packaging/transcription_release_policy.json` approves the recorded v1.0.0
schema-2 inventory digest only; a changed digest fails closed.
