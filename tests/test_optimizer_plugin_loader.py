from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from optimization.plugin_loader import (
    OptimizerBundleError,
    discover_optimizer_bundles,
    load_optimizer_bundle,
    read_bundle_manifest,
)


def manifest(plugin_id="test-plugin"):
    return {
        "schema_version": 1,
        "plugin_id": plugin_id,
        "version": "1.0.0",
        "display_name": "Test Plugin",
        "description": "fixture",
        "api_version": 1,
        "entrypoint": "entry:create_plugin",
        "intensities": ["conservative", "balanced", "deep"],
        "scopes": ["global"],
        "capabilities": ["diagnostic"],
        "requires_safe_prepass": False,
    }


def write_bundle(path: Path, plugin_id="test-plugin", entry="") -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest(plugin_id)))
        archive.writestr("payload/entry.py", entry or (
            "class Plugin:\n"
            "    def analyse(self, request, environment): return None\n"
            "def create_plugin(): return Plugin()\n"
        ))
    return path


class OptimizerPluginLoaderTests(unittest.TestCase):
    def test_discovery_reads_manifest_without_executing_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "executed"
            write_bundle(root / "test.bdoopt", entry=(
                f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
                "class Plugin:\n"
                "    def analyse(self, request, environment): return None\n"
                "def create_plugin(): return Plugin()\n"
            ))
            discovery = discover_optimizer_bundles(root)
            self.assertEqual(len(discovery.bundles), 1)
            self.assertFalse(marker.exists())
            with patch.dict(os.environ, {"BDO_OPTIMIZER_CACHE": str(root / "cache")}):
                load_optimizer_bundle(discovery.bundles[0])
            self.assertTrue(marker.exists())

    def test_duplicate_ids_and_corrupt_bundles_are_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_bundle(root / "a.bdoopt")
            write_bundle(root / "b.bdoopt")
            (root / "broken.bdoopt").write_bytes(b"not zip")
            discovery = discover_optimizer_bundles(root)
            self.assertFalse(discovery.bundles)
            self.assertEqual(len(discovery.diagnostics), 2)

    def test_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.bdoopt"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("manifest.json", json.dumps(manifest()))
                archive.writestr("../escape.py", "")
            with self.assertRaisesRegex(OptimizerBundleError, "unsafe"):
                read_bundle_manifest(path)

    def test_manifest_version_cannot_escape_the_cache_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe-version.bdoopt"
            payload = manifest()
            payload["version"] = "../../outside"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("manifest.json", json.dumps(payload))
                archive.writestr("payload/entry.py", "")
            with self.assertRaisesRegex(OptimizerBundleError, "path-safe"):
                read_bundle_manifest(path)


if __name__ == "__main__":
    unittest.main()
