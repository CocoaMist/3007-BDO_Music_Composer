"""Human-readable third-party credits shown by the desktop application.

The generated build inventory remains the authoritative list for one exact
executable.  This module is the stable, curated acknowledgement layer: every
software or research entry includes a resolvable GitHub link and an explicit
license/usage label so the UI never relies on unlinked names.
"""

from __future__ import annotations

from dataclasses import dataclass


TRANSCRIPTION_SECTION = "transcription"
APPLICATION_SECTION = "application"
RESEARCH_SECTION = "research"

CREDIT_SECTION_SOURCES = (
    (TRANSCRIPTION_SECTION, "自动扒谱、音频与科学计算"),
    (APPLICATION_SECTION, "应用运行、界面与打包"),
    (RESEARCH_SECTION, "格式研究、引用与开发协作"),
)


@dataclass(frozen=True, slots=True)
class CreditEntry:
    section: str
    name: str
    license_label: str
    github_url: str


@dataclass(frozen=True, slots=True)
class ResearchCitation:
    name: str
    citation: str
    github_url: str
    publication_url: str


CREDIT_ENTRIES = (
    CreditEntry(
        TRANSCRIPTION_SECTION,
        "Spotify Basic Pitch 0.4.0 + nmp.onnx",
        "Apache-2.0",
        "https://github.com/spotify/basic-pitch",
    ),
    CreditEntry(
        TRANSCRIPTION_SECTION,
        "Microsoft ONNX Runtime",
        "MIT",
        "https://github.com/microsoft/onnxruntime",
    ),
    CreditEntry(
        TRANSCRIPTION_SECTION,
        "librosa",
        "ISC",
        "https://github.com/librosa/librosa",
    ),
    CreditEntry(
        TRANSCRIPTION_SECTION,
        "SoundFile",
        "BSD-3-Clause",
        "https://github.com/bastibe/python-soundfile",
    ),
    CreditEntry(
        TRANSCRIPTION_SECTION,
        "libsndfile",
        "LGPL-2.1-or-later",
        "https://github.com/libsndfile/libsndfile",
    ),
    CreditEntry(
        TRANSCRIPTION_SECTION,
        "python-soxr",
        "LGPL-2.1-or-later",
        "https://github.com/dofuuz/python-soxr",
    ),
    CreditEntry(
        TRANSCRIPTION_SECTION,
        "libsoxr",
        "LGPL-2.1-or-later",
        "https://github.com/chirlu/soxr",
    ),
    CreditEntry(
        TRANSCRIPTION_SECTION,
        "NumPy",
        "BSD-3-Clause + bundled notices",
        "https://github.com/numpy/numpy",
    ),
    CreditEntry(
        TRANSCRIPTION_SECTION,
        "SciPy",
        "BSD-3-Clause + bundled notices",
        "https://github.com/scipy/scipy",
    ),
    CreditEntry(
        TRANSCRIPTION_SECTION,
        "scikit-learn",
        "BSD-3-Clause",
        "https://github.com/scikit-learn/scikit-learn",
    ),
    CreditEntry(
        TRANSCRIPTION_SECTION,
        "Numba",
        "BSD-2-Clause",
        "https://github.com/numba/numba",
    ),
    CreditEntry(
        TRANSCRIPTION_SECTION,
        "llvmlite",
        "BSD-2-Clause + Apache-2.0 WITH LLVM-exception",
        "https://github.com/numba/llvmlite",
    ),
    CreditEntry(
        TRANSCRIPTION_SECTION,
        "mir_eval",
        "MIT",
        "https://github.com/mir-evaluation/mir_eval",
    ),
    CreditEntry(
        TRANSCRIPTION_SECTION,
        "pretty_midi",
        "MIT",
        "https://github.com/craffel/pretty-midi",
    ),
    CreditEntry(
        TRANSCRIPTION_SECTION,
        "resampy",
        "ISC",
        "https://github.com/bmcfee/resampy",
    ),
    CreditEntry(
        APPLICATION_SECTION,
        "CPython",
        "PSF-2.0",
        "https://github.com/python/cpython",
    ),
    CreditEntry(
        APPLICATION_SECTION,
        "PySide6 / Qt",
        "LGPL-3.0/GPL (module-specific)",
        "https://github.com/qt",
    ),
    CreditEntry(
        APPLICATION_SECTION,
        "Mido",
        "MIT",
        "https://github.com/mido/mido",
    ),
    CreditEntry(
        APPLICATION_SECTION,
        "Pillow",
        "MIT-CMU",
        "https://github.com/python-pillow/Pillow",
    ),
    CreditEntry(
        APPLICATION_SECTION,
        "PyInstaller",
        "GPL-2.0-or-later with special exception",
        "https://github.com/pyinstaller/pyinstaller",
    ),
    CreditEntry(
        APPLICATION_SECTION,
        "Setuptools",
        "MIT",
        "https://github.com/pypa/setuptools",
    ),
    CreditEntry(
        APPLICATION_SECTION,
        "typing_extensions",
        "PSF-2.0",
        "https://github.com/python/typing_extensions",
    ),
    CreditEntry(
        RESEARCH_SECTION,
        "iDevelopThings / bdo-data-extractor",
        "仅作引用；采用上游条款",
        "https://github.com/iDevelopThings/bdo-data-extractor",
    ),
    CreditEntry(
        RESEARCH_SECTION,
        "Bishop-R / historical midi-to-bdo research",
        "仅作引用；未捆绑代码",
        "https://github.com/Bishop-R",
    ),
    CreditEntry(
        RESEARCH_SECTION,
        "Skyro468 / historical BDO music research",
        "仅作引用；未捆绑代码",
        "https://github.com/Skyro468",
    ),
    CreditEntry(
        RESEARCH_SECTION,
        "OpenAI",
        "开发致谢；无运行时依赖",
        "https://github.com/openai",
    ),
)


BASIC_PITCH_MODEL_URL = (
    "https://github.com/spotify/basic-pitch/blob/v0.4.0/"
    "basic_pitch/saved_models/icassp_2022/nmp.onnx"
)
BASIC_PITCH_LICENSE_URL = (
    "https://github.com/spotify/basic-pitch/blob/v0.4.0/LICENSE"
)
BASIC_PITCH_NOTICE_URL = (
    "https://github.com/spotify/basic-pitch/blob/v0.4.0/NOTICE"
)

RESEARCH_CITATIONS = (
    ResearchCitation(
        name="Basic Pitch",
        citation=(
            "Bittner, R. M.; Bosch, J. J.; Rubinstein, D.; "
            "Meseguer-Brocal, G.; Ewert, S. “A Lightweight "
            "Instrument-Agnostic Model for Polyphonic Note Transcription "
            "and Multipitch Estimation.” ICASSP 2022."
        ),
        github_url="https://github.com/spotify/basic-pitch",
        publication_url="https://arxiv.org/abs/2203.09893",
    ),
)


__all__ = [
    "APPLICATION_SECTION",
    "BASIC_PITCH_LICENSE_URL",
    "BASIC_PITCH_MODEL_URL",
    "BASIC_PITCH_NOTICE_URL",
    "CREDIT_ENTRIES",
    "CREDIT_SECTION_SOURCES",
    "CreditEntry",
    "RESEARCH_CITATIONS",
    "RESEARCH_SECTION",
    "ResearchCitation",
    "TRANSCRIPTION_SECTION",
]
