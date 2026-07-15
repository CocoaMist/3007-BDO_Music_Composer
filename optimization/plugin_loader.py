"""Discovery, validation, extraction, and lazy loading of .bdoopt bundles."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
from types import ModuleType
from typing import Any
import zipfile

from .plugin_api import ALL_INTENSITIES, PLUGIN_API_VERSION, PluginEnvironment, VALID_SCOPES


BUNDLE_SCHEMA_VERSION = 1
MAX_BUNDLE_FILES = 50_000
MAX_UNCOMPRESSED_BYTES = 16 * 1024**3
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_MANIFEST_FIELDS = {
    "schema_version", "plugin_id", "version", "display_name", "description",
    "api_version", "entrypoint", "intensities", "scopes", "capabilities",
    "requires_safe_prepass",
}


class OptimizerBundleError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OptimizerBundleManifest:
    schema_version: int
    plugin_id: str
    version: str
    display_name: str
    description: str
    api_version: int
    entrypoint: str
    intensities: tuple[str, ...]
    scopes: tuple[str, ...]
    capabilities: tuple[str, ...]
    requires_safe_prepass: bool


@dataclass(frozen=True, slots=True)
class OptimizerBundleDescriptor:
    path: Path
    manifest: OptimizerBundleManifest


@dataclass(frozen=True, slots=True)
class BundleDiscovery:
    bundles: tuple[OptimizerBundleDescriptor, ...]
    diagnostics: tuple[str, ...]


def optimizer_plugin_dir() -> Path:
    configured = os.environ.get("BDO_OPTIMIZER_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    local = os.environ.get("LOCALAPPDATA", "").strip()
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return base / "BDO Music Composer" / "optimizer_plugins"


def optimizer_cache_dir() -> Path:
    configured = os.environ.get("BDO_OPTIMIZER_CACHE", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return optimizer_plugin_dir().parent / "optimizer_cache"


def _validate_member(info: zipfile.ZipInfo) -> None:
    path = PurePosixPath(info.filename.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or (path.parts and ":" in path.parts[0]):
        raise OptimizerBundleError(f"unsafe bundle path: {info.filename}")
    if (info.external_attr >> 16) & 0o170000 == 0o120000:
        raise OptimizerBundleError(f"symbolic links are not allowed in bundles: {info.filename}")


def _manifest(payload: dict[str, Any]) -> OptimizerBundleManifest:
    unknown = set(payload) - _MANIFEST_FIELDS
    missing = _MANIFEST_FIELDS - set(payload)
    if unknown or missing:
        raise OptimizerBundleError(f"manifest fields invalid; missing={sorted(missing)}, unknown={sorted(unknown)}")
    if payload["schema_version"] != BUNDLE_SCHEMA_VERSION:
        raise OptimizerBundleError(f"unsupported bundle schema: {payload['schema_version']!r}")
    if payload["api_version"] != PLUGIN_API_VERSION:
        raise OptimizerBundleError(f"unsupported optimizer API: {payload['api_version']!r}")
    plugin_id = str(payload["plugin_id"]).strip().lower()
    if not _ID_PATTERN.fullmatch(plugin_id):
        raise OptimizerBundleError("plugin_id must be a stable lowercase identifier")
    version = str(payload["version"]).strip()
    if not _VERSION_PATTERN.fullmatch(version):
        raise OptimizerBundleError("version must be a path-safe identifier")
    if not isinstance(payload["intensities"], list) or not isinstance(payload["scopes"], list):
        raise OptimizerBundleError("intensities and scopes must be arrays")
    if not isinstance(payload["capabilities"], list):
        raise OptimizerBundleError("capabilities must be an array")
    if not isinstance(payload["requires_safe_prepass"], bool):
        raise OptimizerBundleError("requires_safe_prepass must be a boolean")
    intensities = tuple(str(item) for item in payload["intensities"])
    if set(intensities) != set(ALL_INTENSITIES) or len(intensities) != len(ALL_INTENSITIES):
        raise OptimizerBundleError("plugins must support conservative, balanced, and deep")
    scopes = tuple(str(item) for item in payload["scopes"])
    if not scopes or len(set(scopes)) != len(scopes) or not set(scopes).issubset(VALID_SCOPES):
        raise OptimizerBundleError("plugin scopes are invalid")
    entrypoint = str(payload["entrypoint"])
    if entrypoint.count(":") != 1 or not entrypoint.split(":")[0]:
        raise OptimizerBundleError("entrypoint must use module:function")
    module_name, factory_name = entrypoint.split(":", 1)
    if not factory_name.isidentifier() or not all(part.isidentifier() for part in module_name.split(".")):
        raise OptimizerBundleError("entrypoint contains an invalid Python identifier")
    display_name = str(payload["display_name"]).strip()
    if not display_name:
        raise OptimizerBundleError("display_name must not be empty")
    return OptimizerBundleManifest(
        BUNDLE_SCHEMA_VERSION, plugin_id, version, display_name,
        str(payload["description"]), PLUGIN_API_VERSION, entrypoint, intensities, scopes,
        tuple(str(item) for item in payload["capabilities"]), bool(payload["requires_safe_prepass"]),
    )


def read_bundle_manifest(path: Path) -> OptimizerBundleManifest:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_BUNDLE_FILES:
                raise OptimizerBundleError("bundle contains too many files")
            total = 0
            for info in infos:
                _validate_member(info)
                total += info.file_size
                if total > MAX_UNCOMPRESSED_BYTES:
                    raise OptimizerBundleError("bundle expands beyond the 16 GiB limit")
            if "manifest.json" not in archive.namelist():
                raise OptimizerBundleError("bundle is missing manifest.json")
            payload = json.loads(archive.read("manifest.json").decode("utf-8"))
    except (OSError, zipfile.BadZipFile, UnicodeError, json.JSONDecodeError) as exc:
        raise OptimizerBundleError(f"cannot read optimizer bundle: {exc}") from exc
    if not isinstance(payload, dict):
        raise OptimizerBundleError("manifest root must be an object")
    return _manifest(payload)


def discover_optimizer_bundles(directory: Path | None = None) -> BundleDiscovery:
    directory = directory or optimizer_plugin_dir()
    if not directory.exists():
        return BundleDiscovery((), ())
    found: list[OptimizerBundleDescriptor] = []
    diagnostics: list[str] = []
    by_id: dict[str, list[OptimizerBundleDescriptor]] = {}
    for path in sorted(directory.glob("*.bdoopt"), key=lambda item: item.name.lower()):
        try:
            descriptor = OptimizerBundleDescriptor(path.resolve(), read_bundle_manifest(path))
            by_id.setdefault(descriptor.manifest.plugin_id, []).append(descriptor)
        except OptimizerBundleError as exc:
            diagnostics.append(f"{path.name}: {exc}")
    for plugin_id, descriptors in sorted(by_id.items()):
        if len(descriptors) != 1:
            diagnostics.append(f"{plugin_id}: duplicate plugin ID; all copies disabled")
            continue
        found.append(descriptors[0])
    found.sort(key=lambda item: (item.manifest.display_name.casefold(), item.manifest.plugin_id))
    return BundleDiscovery(tuple(found), tuple(diagnostics))


def _bundle_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract(descriptor: OptimizerBundleDescriptor) -> tuple[Path, str]:
    digest = _bundle_digest(descriptor.path)
    target = optimizer_cache_dir() / descriptor.manifest.plugin_id / descriptor.manifest.version / digest
    marker = target / ".complete"
    if marker.is_file():
        return target, digest
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(descriptor.path) as archive:
        for info in archive.infolist():
            _validate_member(info)
            archive.extract(info, target)
    marker.touch()
    return target, digest


def load_optimizer_bundle(descriptor: OptimizerBundleDescriptor) -> tuple[object, PluginEnvironment]:
    root, digest = _extract(descriptor)
    payload = root / "payload"
    if not payload.is_dir():
        raise OptimizerBundleError("bundle is missing payload/")
    namespace = f"_bdoopt_{descriptor.manifest.plugin_id.replace('-', '_').replace('.', '_')}_{digest[:12]}"
    package = sys.modules.get(namespace)
    if package is None:
        package = ModuleType(namespace)
        package.__path__ = [str(payload)]  # type: ignore[attr-defined]
        package.__package__ = namespace
        sys.modules[namespace] = package
    module_name, factory_name = descriptor.manifest.entrypoint.split(":", 1)
    module = importlib.import_module(f"{namespace}.{module_name}")
    factory = getattr(module, factory_name, None)
    if not callable(factory):
        raise OptimizerBundleError(f"entrypoint is not callable: {descriptor.manifest.entrypoint}")
    plugin = factory()
    if not callable(getattr(plugin, "analyse", None)):
        raise OptimizerBundleError("plugin object must provide analyse(request, environment)")
    return plugin, PluginEnvironment(root)
