#!/usr/bin/env python3
"""Build a deterministic, privacy-filtered source SDK archive."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import sys
import tempfile
from typing import Iterable
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bdo_music_composer.app.application_metadata import APP_NAME, APP_VERSION
from bdo_music_composer.sdk.core_api import SDK_API_VERSION


ARCHIVE_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
ARCHIVE_PREFIX = f"BDO-Music-Composer-Developer-SDK-{APP_VERSION}"

SOURCE_DIRECTORIES = (
    "src/bdo_common",
    "src/bdo_codec",
    "src/bdo_export",
    "src/bdo_midi",
    "src/bdo_music_composer",
    "src/optimization",
    "assets",
    "data/codec",
    "data/mappings",
    "data/profiles",
    "docs",
    "examples/sdk",
    "packaging/developer_sdk",
    "tests",
)
ROOT_FILES = (
    "AGENTS.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.md",
    "THIRD_PARTY_NOTICES.md",
    "requirements/windows-py312.txt",
    "main.py",
    "requirements/desktop.txt",
    "requirements/transcription.txt",
)
FORBIDDEN_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "auto_save",
        "build",
        "dist",
        "out",
        "releases",
    }
)
FORBIDDEN_SUFFIXES = frozenset(
    {
        ".7z",
        ".bdo",
        ".bdoopt",
        ".bdosamples",
        ".bnk",
        ".dll",
        ".exe",
        ".flac",
        ".mid",
        ".midi",
        ".mp3",
        ".ogg",
        ".pdb",
        ".rar",
        ".wav",
        ".wem",
        ".zip",
    }
)
FORBIDDEN_FILENAMES = frozenset(
    {
        ".pyside_bdo_gui.json",
        "release_notes.json",
    }
)


@dataclass(frozen=True, slots=True)
class PayloadFile:
    path: PurePosixPath
    data: bytes


def _is_allowed(relative_path: PurePosixPath) -> bool:
    lowered_parts = tuple(part.lower() for part in relative_path.parts)
    return not (
        FORBIDDEN_PARTS.intersection(lowered_parts)
        or relative_path.name.lower() in FORBIDDEN_FILENAMES
        or relative_path.suffix.lower() in FORBIDDEN_SUFFIXES
    )


def _source_files() -> Iterable[PayloadFile]:
    seen: set[PurePosixPath] = set()
    for relative_root in SOURCE_DIRECTORIES:
        directory = ROOT / relative_root
        if not directory.is_dir():
            continue
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            relative_path = PurePosixPath(path.relative_to(ROOT).as_posix())
            if relative_path in seen or not _is_allowed(relative_path):
                continue
            seen.add(relative_path)
            yield PayloadFile(relative_path, path.read_bytes())
    for filename in ROOT_FILES:
        path = ROOT / filename
        if not path.is_file():
            raise FileNotFoundError(f"required SDK file is missing: {filename}")
        relative_path = PurePosixPath(filename)
        if relative_path not in seen and _is_allowed(relative_path):
            yield PayloadFile(relative_path, path.read_bytes())


def _generated_pyproject() -> bytes:
    return f'''[build-system]
requires = ["setuptools>=75", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "bdo-music-composer-sdk"
version = "{APP_VERSION}"
description = "Source SDK for BDO Music Composer core and optional PySide6 UI"
readme = "SDK_README.md"
requires-python = ">=3.12,<3.13"
license = {{file = "LICENSE"}}
dependencies = ["mido", "numpy"]

[project.optional-dependencies]
ui = ["PySide6"]
transcription = [
  "librosa==0.11.0",
  "mir-eval==0.8.2",
  "onnxruntime==1.27.0",
  "pretty-midi==0.2.11",
  "resampy==0.4.2",
  "scikit-learn==1.9.0",
  "scipy==1.18.0",
  "soundfile==0.14.0",
  "soxr==1.1.0",
]

[tool.setuptools]
package-dir = {{"" = "src"}}

[tool.setuptools.packages.find]
where = ["src"]
include = [
  "bdo_common*",
  "bdo_codec*",
  "bdo_export*",
  "bdo_midi*",
  "bdo_music_composer*",
  "optimization*",
]

[tool.setuptools.package-data]
"*" = ["*.json", "*.png", "*.ico", "*.jpg", "*.tsv"]
'''.encode("utf-8")


def _generated_readme() -> bytes:
    return f'''# {APP_NAME} Developer SDK {APP_VERSION}

This source SDK contains the Qt-free codec/editor/export core, optional PySide6
UI components, examples, documentation, regression tests, and required public
resources. SDK API level: `{SDK_API_VERSION}`.

## Install

```powershell
py -3.12 -m venv .venv
.\\.venv\\Scripts\\python.exe -m pip install -e .
# Add reusable UI widgets and the desktop application:
.\\.venv\\Scripts\\python.exe -m pip install -e ".[ui]"
```

Import stable integration symbols from
`bdo_music_composer.sdk.core_api`. Import lazy UI helpers from
`bdo_music_composer.sdk.ui_api`. See `docs/DEVELOPER_SDK.md` and
`examples/sdk/` before depending on internal modules.

The archive contains no score, Owner ID, character name, game audio, local
configuration, autosave, executable, or release ZIP. Verify its inventory with
`SDK_MANIFEST.json`.
'''.encode("utf-8")


def _manifest(payload: list[PayloadFile]) -> bytes:
    document = {
        "schema": 1,
        "application": APP_NAME,
        "application_version": APP_VERSION,
        "sdk_api_version": SDK_API_VERSION,
        "archive_root": ARCHIVE_PREFIX,
        "files": [
            {
                "path": item.path.as_posix(),
                "size": len(item.data),
                "sha256": sha256(item.data).hexdigest(),
            }
            for item in payload
        ],
    }
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _zip_info(name: str) -> ZipInfo:
    info = ZipInfo(name, ARCHIVE_TIMESTAMP)
    info.compress_type = ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def build_sdk(output: Path) -> Path:
    """Build one deterministic SDK ZIP and return its resolved path."""

    payload = list(_source_files())
    generated = (
        PayloadFile(PurePosixPath("pyproject.toml"), _generated_pyproject()),
        PayloadFile(PurePosixPath("SDK_README.md"), _generated_readme()),
    )
    payload.extend(generated)
    payload.sort(key=lambda item: item.path.as_posix())
    for item in payload:
        if not _is_allowed(item.path):
            raise ValueError(f"forbidden SDK payload: {item.path}")
    manifest = PayloadFile(PurePosixPath("SDK_MANIFEST.json"), _manifest(payload))

    destination = output.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with ZipFile(temporary_path, "w", allowZip64=True) as archive:
            for item in (*payload, manifest):
                archive_path = f"{ARCHIVE_PREFIX}/{item.path.as_posix()}"
                archive.writestr(_zip_info(archive_path), item.data)
        temporary_path.replace(destination)
    finally:
        temporary_path.unlink(missing_ok=True)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dist" / "sdk" / f"{ARCHIVE_PREFIX}.zip",
    )
    args = parser.parse_args()
    result = build_sdk(args.output)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
