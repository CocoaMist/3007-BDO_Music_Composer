"""Generate the exact bundled transcription dependency inventory.

The report is intentionally generated from the interpreter used for the build.
It is evidence for a human license review, not a substitute for that review.
The public-release gate remains fail-closed until the checked-in policy names
the approved inventory digest.
"""

from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import re
import shutil
import sys
from typing import Any, Iterable

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name


INVENTORY_SCHEMA = 1
DEFAULT_ROOT_DISTRIBUTIONS = (
    "basic-pitch",
    "onnxruntime",
    "librosa",
    "mir-eval",
    "pretty-midi",
    "resampy",
    "scikit-learn",
    "scipy",
    "setuptools",
    "soundfile",
    "soxr",
    "typing-extensions",
)

# Basic Pitch 0.4.0 declares TensorFlow for Python 3.11+ even though this
# application constructs only its ONNX session. These backends and their model
# formats are intentionally excluded from the transcription-enabled build.
NON_ONNX_BACKEND_DISTRIBUTIONS = frozenset(
    canonicalize_name(name)
    for name in (
        "tensorflow",
        "tensorflow-cpu",
        "tensorflow-intel",
        "tensorflow-macos",
        "coremltools",
        "tflite-runtime",
    )
)

_LICENSE_NAME = re.compile(
    (
        r"^(?:licen[cs]e|copying|notices?|copyright|authors?|"
        r"third[._ -]*party[._ -]*notices?)(?:[._-].*)?$"
    ),
    re.IGNORECASE,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _distribution_license_files(
    distribution: metadata.Distribution,
) -> tuple[Path, ...]:
    matches: list[Path] = []
    for relative in distribution.files or ():
        relative_path = Path(str(relative))
        path_parts = {part.lower() for part in relative_path.parts}
        is_license_dir = "licenses" in path_parts
        is_notice_name = bool(_LICENSE_NAME.match(relative_path.name))
        if not (is_license_dir or is_notice_name):
            continue
        absolute = Path(distribution.locate_file(relative))
        if absolute.is_file():
            matches.append(absolute)
    return tuple(sorted(set(matches), key=lambda path: str(path).lower()))


def _declared_license(distribution: metadata.Distribution) -> str:
    package_metadata = distribution.metadata
    expression = str(package_metadata.get("License-Expression") or "").strip()
    if expression:
        return expression

    license_field = str(package_metadata.get("License") or "").strip()
    if license_field and "\n" not in license_field and len(license_field) <= 160:
        return license_field

    classifiers = [
        value.removeprefix("License :: ").strip()
        for value in package_metadata.get_all("Classifier", [])
        if value.startswith("License :: ")
    ]
    return " | ".join(classifiers) if classifiers else "UNKNOWN"


def _active_requirements(
    distribution: metadata.Distribution,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    environment = default_environment()
    environment["extra"] = ""
    active: set[str] = set()
    ignored_backends: set[str] = set()
    for raw_requirement in distribution.requires or ():
        try:
            requirement = Requirement(raw_requirement)
        except InvalidRequirement:
            continue
        normalized = canonicalize_name(requirement.name)
        if normalized in NON_ONNX_BACKEND_DISTRIBUTIONS:
            ignored_backends.add(normalized)
            continue
        if requirement.marker is not None and not requirement.marker.evaluate(
            environment
        ):
            continue
        active.add(normalized)
    return tuple(sorted(active)), tuple(sorted(ignored_backends))


def _safe_package_dir(name: str, version: str) -> str:
    value = canonicalize_name(name).replace("-", "_")
    version_value = re.sub(r"[^A-Za-z0-9._-]+", "_", version)
    return f"{value}-{version_value}"


def _copy_license_files(
    distribution: metadata.Distribution,
    output_dir: Path,
    name: str,
    version: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    destination_dir = output_dir / "licenses" / _safe_package_dir(name, version)
    used_names: set[str] = set()
    for source in _distribution_license_files(distribution):
        destination_name = source.name
        if destination_name.lower() in used_names:
            destination_name = f"{_sha256(source)[:10]}-{destination_name}"
        used_names.add(destination_name.lower())
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / destination_name
        shutil.copyfile(source, destination)
        records.append(
            {
                "path": destination.relative_to(output_dir).as_posix(),
                "size": destination.stat().st_size,
                "sha256": _sha256(destination),
            }
        )
    return records


def _project_urls(distribution: metadata.Distribution) -> tuple[str, ...]:
    values = []
    for item in distribution.metadata.get_all("Project-URL", []):
        values.append(str(item))
    home_page = str(distribution.metadata.get("Home-page") or "").strip()
    if home_page:
        values.append(f"Home-page, {home_page}")
    return tuple(dict.fromkeys(values))


def _runtime_artifacts() -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    try:
        basic_pitch = metadata.distribution("basic-pitch")
        package_root = Path(basic_pitch.locate_file("basic_pitch"))
        model = package_root / "saved_models" / "icassp_2022" / "nmp.onnx"
        if model.is_file():
            artifacts.append(
                {
                    "kind": "model",
                    "owner_distribution": "basic-pitch",
                    "path": "basic_pitch/saved_models/icassp_2022/nmp.onnx",
                    "size": model.stat().st_size,
                    "sha256": _sha256(model),
                }
            )
    except metadata.PackageNotFoundError:
        pass

    try:
        onnxruntime = metadata.distribution("onnxruntime")
        package_root = Path(onnxruntime.locate_file("onnxruntime"))
        for filename in (
            "onnxruntime.dll",
            "onnxruntime_providers_shared.dll",
        ):
            binary = package_root / "capi" / filename
            if binary.is_file():
                artifacts.append(
                    {
                        "kind": "native-library",
                        "owner_distribution": "onnxruntime",
                        "path": f"onnxruntime/capi/{filename}",
                        "size": binary.stat().st_size,
                        "sha256": _sha256(binary),
                    }
                )
    except metadata.PackageNotFoundError:
        pass
    return artifacts


def build_inventory(
    output_dir: Path,
    roots: Iterable[str] = DEFAULT_ROOT_DISTRIBUTIONS,
) -> dict[str, Any]:
    """Resolve the installed ONNX-only dependency closure and copy notices."""

    output_dir.mkdir(parents=True, exist_ok=True)
    normalized_roots = tuple(sorted({canonicalize_name(name) for name in roots}))
    pending = deque(normalized_roots)
    visited: set[str] = set()
    packages: list[dict[str, Any]] = []
    ignored_backend_dependencies: set[str] = set()

    while pending:
        requested_name = pending.popleft()
        if requested_name in visited:
            continue
        visited.add(requested_name)
        try:
            distribution = metadata.distribution(requested_name)
        except metadata.PackageNotFoundError:
            packages.append(
                {
                    "name": requested_name,
                    "version": None,
                    "declared_license": "MISSING",
                    "license_files": [],
                    "runtime_dependencies": [],
                    "project_urls": [],
                }
            )
            continue

        name = str(distribution.metadata.get("Name") or requested_name)
        version = distribution.version
        dependencies, ignored = _active_requirements(distribution)
        ignored_backend_dependencies.update(ignored)
        pending.extend(
            dependency
            for dependency in dependencies
            if dependency not in visited
        )
        packages.append(
            {
                "name": name,
                "normalized_name": canonicalize_name(name),
                "version": version,
                "declared_license": _declared_license(distribution),
                "license_files": _copy_license_files(
                    distribution,
                    output_dir,
                    name,
                    version,
                ),
                "runtime_dependencies": list(dependencies),
                "project_urls": list(_project_urls(distribution)),
            }
        )

    packages.sort(key=lambda item: str(item["name"]).lower())
    core = {
        "schema": INVENTORY_SCHEMA,
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "roots": list(normalized_roots),
        "ignored_non_onnx_backend_dependencies": sorted(
            ignored_backend_dependencies
        ),
        "packages": packages,
        "runtime_artifacts": _runtime_artifacts(),
    }
    canonical = json.dumps(
        core,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    unresolved = [
        str(package["name"])
        for package in packages
        if package["version"] is None
        or (
            package["declared_license"] in {"UNKNOWN", "MISSING"}
            and not package["license_files"]
        )
    ]
    return {
        **core,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "inventory_sha256": hashlib.sha256(canonical).hexdigest(),
        "unresolved_packages": unresolved,
    }


def release_blockers(
    policy: dict[str, Any],
    inventory: dict[str, Any],
) -> tuple[str, ...]:
    blockers: list[str] = []
    if policy.get("public_release_cleared") is not True:
        blockers.append("public_release_cleared is not true")
    approved_digest = str(policy.get("approved_inventory_sha256") or "")
    if not approved_digest:
        blockers.append("approved_inventory_sha256 is empty")
    elif approved_digest != inventory.get("inventory_sha256"):
        blockers.append("installed dependency inventory is not the approved digest")
    if inventory.get("unresolved_packages"):
        blockers.append(
            "dependency licenses are unresolved: "
            + ", ".join(inventory["unresolved_packages"])
        )
    if not str(policy.get("reviewed_by") or "").strip():
        blockers.append("reviewed_by is empty")
    if not str(policy.get("reviewed_at_utc") or "").strip():
        blockers.append("reviewed_at_utc is empty")
    if policy.get("notice_files_verified") is not True:
        blockers.append("notice_files_verified is not true")
    if policy.get("model_redistribution_reviewed") is not True:
        blockers.append("model_redistribution_reviewed is not true")
    if policy.get("native_library_notices_reviewed") is not True:
        blockers.append("native_library_notices_reviewed is not true")
    return tuple(blockers)


def write_inventory(output_dir: Path, inventory: dict[str, Any]) -> None:
    json_path = output_dir / "transcription-dependency-inventory.json"
    json_path.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Bundled transcription dependency inventory",
        "",
        "Generated from the exact Python environment used for this build.",
        "This report is not a legal approval.",
        "",
        f"- Inventory SHA-256: `{inventory['inventory_sha256']}`",
        f"- Python: `{inventory['python']}`",
        f"- Packages: {len(inventory['packages'])}",
        "",
        "| Package | Version | Declared license | Notice files |",
        "|---|---:|---|---:|",
    ]
    for package in inventory["packages"]:
        lines.append(
            "| {name} | {version} | {license} | {files} |".format(
                name=str(package["name"]).replace("|", "\\|"),
                version=package["version"] or "MISSING",
                license=str(package["declared_license"]).replace("|", "\\|"),
                files=len(package["license_files"]),
            )
        )
    lines.extend(
        [
            "",
            "Non-ONNX backends intentionally excluded: "
            + ", ".join(inventory["ignored_non_onnx_backend_dependencies"]),
            "",
        ]
    )
    if inventory["unresolved_packages"]:
        lines.extend(
            [
                "Unresolved packages: "
                + ", ".join(inventory["unresolved_packages"]),
                "",
            ]
        )
    (output_dir / "README.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--policy",
        type=Path,
        default=project_root
        / "packaging"
        / "transcription_release_policy.json",
    )
    parser.add_argument(
        "--require-public-clearance",
        action="store_true",
        help="Fail unless the checked-in policy approves this exact inventory.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    inventory = build_inventory(args.output_dir)
    write_inventory(args.output_dir, inventory)
    print(
        "Transcription dependency inventory: "
        f"{inventory['inventory_sha256']}"
    )
    if args.require_public_clearance:
        try:
            policy = json.loads(args.policy.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"Public release blocked: invalid policy: {exc}", file=sys.stderr)
            return 2
        blockers = release_blockers(policy, inventory)
        if blockers:
            print("Public release blocked:", file=sys.stderr)
            for blocker in blockers:
                print(f"- {blocker}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
