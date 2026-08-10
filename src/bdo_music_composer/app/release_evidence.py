"""Deterministic release evidence for a frozen Windows artifact."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.metadata
import json
from pathlib import Path
from typing import Iterable

from bdo_common.atomic_io import atomic_write_bytes
from bdo_music_composer.app.application_metadata import APP_NAME, APP_VERSION


RELEASE_EVIDENCE_SCHEMA = 1
SPDX_VERSION = "SPDX-2.3"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class InstalledPackage:
    name: str
    version: str
    license_expression: str


def installed_packages() -> tuple[InstalledPackage, ...]:
    packages: list[InstalledPackage] = []
    for distribution in importlib.metadata.distributions():
        name = str(distribution.metadata.get("Name") or "").strip()
        if not name:
            continue
        license_value = str(
            distribution.metadata.get("License-Expression")
            or "NOASSERTION"
        ).strip()
        packages.append(InstalledPackage(name, distribution.version, license_value))
    return tuple(sorted(packages, key=lambda item: (item.name.casefold(), item.version)))


def build_spdx_document(
    artifact: str | Path,
    packages: Iterable[InstalledPackage] | None = None,
) -> dict[str, object]:
    artifact_path = Path(artifact)
    artifact_digest = sha256_file(artifact_path)
    package_values = tuple(packages) if packages is not None else installed_packages()
    return {
        "spdxVersion": SPDX_VERSION,
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{APP_NAME}-{APP_VERSION}",
        "documentNamespace": (
            "https://github.com/CocoaMist/3007-BDO_Music_Composer/"
            f"releases/{APP_VERSION}/{artifact_digest}"
        ),
        "creationInfo": {
            "creators": ["Tool: BDO-Music-Composer-release-evidence/1"],
        },
        "packages": [
            {
                "name": item.name,
                "SPDXID": f"SPDXRef-Package-{index}",
                "versionInfo": item.version,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": item.license_expression or "NOASSERTION",
            }
            for index, item in enumerate(package_values, start=1)
        ],
        "files": [
            {
                "fileName": artifact_path.name,
                "SPDXID": "SPDXRef-ReleaseArtifact",
                "checksums": [
                    {"algorithm": "SHA256", "checksumValue": artifact_digest}
                ],
            }
        ],
        "relationships": [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": "SPDXRef-ReleaseArtifact",
            },
            *(
                {
                    "spdxElementId": "SPDXRef-ReleaseArtifact",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": f"SPDXRef-Package-{index}",
                }
                for index in range(1, len(package_values) + 1)
            ),
        ],
    }


def write_release_evidence(
    artifact: str | Path,
    output_directory: str | Path,
) -> tuple[Path, Path]:
    artifact_path = Path(artifact)
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    digest = sha256_file(artifact_path)
    checksum_path = output / f"{artifact_path.name}.sha256"
    sbom_path = output / f"{artifact_path.name}.spdx.json"
    atomic_write_bytes(checksum_path, f"{digest}  {artifact_path.name}\n".encode("ascii"))
    document = build_spdx_document(artifact_path)
    atomic_write_bytes(
        sbom_path,
        (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return checksum_path, sbom_path


__all__ = [
    "InstalledPackage",
    "RELEASE_EVIDENCE_SCHEMA",
    "build_spdx_document",
    "installed_packages",
    "sha256_file",
    "write_release_evidence",
]
