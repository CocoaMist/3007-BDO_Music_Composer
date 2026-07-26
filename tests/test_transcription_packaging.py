from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import main as application_entry
from scripts.audit_transcription_licenses import (
    build_inventory,
    release_blockers,
    write_inventory,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TranscriptionPackagingTests(unittest.TestCase):
    def test_unified_spec_bundles_onnx_transcription_runtime(self) -> None:
        spec = (
            PROJECT_ROOT / "packaging" / "windows" / "BDOMusicComposer.spec"
        ).read_text(encoding="utf-8")
        self.assertIn('name="BDO-Music-Composer"', spec)
        self.assertIn('"basic_pitch"', spec)
        self.assertIn('"onnxruntime"', spec)
        self.assertIn('"soundfile"', spec)
        self.assertIn('"soxr"', spec)
        self.assertIn('"nmp.onnx"', spec)
        self.assertIn('collect_dynamic_libs("onnxruntime")', spec)
        self.assertIn('"tensorflow"', spec)
        self.assertNotIn('"nmp.tflite"', spec)
        self.assertNotIn('"nmp.mlpackage"', spec)
        self.assertNotIn("standard_edition_excludes", spec)
        self.assertNotIn("BDO-Music-Composer-LOCAL", spec)
        self.assertNotIn('"unittest"', spec)

    def test_original_visual_resources_are_bundled(self) -> None:
        spec = (
            PROJECT_ROOT / "packaging" / "windows" / "BDOMusicComposer.spec"
        ).read_text(encoding="utf-8")
        self.assertIn('"timeline_background_v2.png"', spec)
        self.assertIn('"assets" / "instruments" / "ai_v1"', spec)
        self.assertTrue(
            (
                PROJECT_ROOT
                / "assets"
                / "ui"
                / "timeline_background_v2.png"
            ).is_file()
        )
        icon_root = PROJECT_ROOT / "assets" / "instruments" / "ai_v1"
        self.assertEqual(12, len(tuple(icon_root.glob("*.png"))))

    def test_single_build_entry_uses_unified_spec_and_product_name(self) -> None:
        build_script = (
            PROJECT_ROOT
            / "packaging"
            / "windows"
            / "build.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn('"BDOMusicComposer.spec"', build_script)
        self.assertIn(
            '$OutputExecutable = Join-Path $ProjectRoot '
            '"dist\\BDO-Music-Composer.exe"',
            build_script,
        )
        self.assertIn("Cannot replace $OutputExecutable", build_script)
        self.assertIn('"--require-public-clearance"', build_script)
        self.assertIn("scripts\\install_transcription.ps1 first", build_script)
        self.assertIn("--workpath $BuildWork", build_script)
        self.assertIn('"bdo-music-composer-build-"', build_script)
        self.assertIn("Remove-Item -LiteralPath $ResolvedBuildWork", build_script)
        self.assertIn(
            '-ArgumentList "--self-test-transcription"',
            build_script,
        )
        self.assertIn("Frozen transcription self-test failed", build_script)
        self.assertIn(
            '-ArgumentList "--self-test-startup"',
            build_script,
        )
        self.assertGreaterEqual(build_script.count("Start-Process"), 2)
        self.assertGreaterEqual(build_script.count("-WindowStyle Hidden"), 2)
        self.assertGreaterEqual(build_script.count("-Wait"), 2)
        self.assertGreaterEqual(build_script.count("-PassThru"), 2)
        self.assertNotIn("& $OutputExecutable", build_script)
        self.assertIn("Frozen 10-second startup self-test failed", build_script)
        self.assertIn('$env:QT_QPA_PLATFORM = "offscreen"', build_script)
        self.assertIn("$env:BDO_USER_DATA_DIR = $StartupSmokeRoot", build_script)
        self.assertIn(
            "[IO.Directory]::CreateDirectory($StartupSmokeRoot)",
            build_script,
        )
        self.assertNotIn("--workpath build", build_script)
        self.assertNotIn("BDO-Music-Composer-LOCAL", build_script)
        self.assertFalse(
            (
                PROJECT_ROOT
                / "packaging"
                / "windows"
                / "build-transcription.ps1"
            ).exists()
        )
        self.assertFalse(
            (
                PROJECT_ROOT
                / "packaging"
                / "windows"
                / "BDOMusicComposerTranscription.spec"
            ).exists()
        )

    def test_checked_in_policy_blocks_public_release(self) -> None:
        policy = json.loads(
            (
                PROJECT_ROOT
                / "packaging"
                / "transcription_release_policy.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(policy["product"], "BDO Music Composer")
        self.assertEqual(policy["artifact"], "BDO-Music-Composer.exe")
        self.assertNotIn("edition", policy)
        inventory = {
            "inventory_sha256": "test-digest",
            "unresolved_packages": [],
        }
        blockers = release_blockers(policy, inventory)
        self.assertIn("public_release_cleared is not true", blockers)
        self.assertIn("approved_inventory_sha256 is empty", blockers)

    def test_missing_distribution_remains_visible_and_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            inventory = build_inventory(
                output_dir,
                roots=("bdo-package-that-must-not-exist",),
            )
            self.assertEqual(
                inventory["unresolved_packages"],
                ["bdo-package-that-must-not-exist"],
            )
            package = inventory["packages"][0]
            self.assertIsNone(package["version"])
            self.assertEqual(package["declared_license"], "MISSING")

            write_inventory(output_dir, inventory)
            self.assertTrue(
                (output_dir / "transcription-dependency-inventory.json").is_file()
            )
            self.assertTrue((output_dir / "README.md").is_file())
            inventory_text = (
                output_dir / "transcription-dependency-inventory.json"
            ).read_text(encoding="utf-8")
            self.assertNotIn(str(output_dir.resolve()), inventory_text)

    def test_self_test_argument_is_dispatched_before_conversion_cli(self) -> None:
        with (
            patch.object(
                sys,
                "argv",
                ["BDO-Music-Composer", "--self-test-transcription"],
            ),
            patch.object(
                application_entry,
                "_self_test_transcription",
                return_value=0,
            ) as self_test,
        ):
            with self.assertRaisesRegex(SystemExit, "^0$"):
                application_entry.main()
        self_test.assert_called_once_with()

    def test_startup_self_test_argument_is_dispatched_before_cli(self) -> None:
        with (
            patch.object(
                sys,
                "argv",
                ["BDO-Music-Composer", "--self-test-startup"],
            ),
            patch.object(
                application_entry,
                "_self_test_startup",
                return_value=0,
            ) as self_test,
        ):
            with self.assertRaisesRegex(SystemExit, "^0$"):
                application_entry.main()
        self_test.assert_called_once_with()

    def test_startup_self_test_uses_disposable_user_data(self) -> None:
        real_user_data = str(PROJECT_ROOT / "must-not-be-touched")
        observed: dict[str, Path | str] = {}

        def probe() -> int:
            isolated = Path(os.environ["BDO_USER_DATA_DIR"])
            observed["path"] = isolated
            observed["platform"] = os.environ["QT_QPA_PLATFORM"]
            observed["self_test"] = os.environ["BDO_STARTUP_SELF_TEST"]
            self.assertNotEqual(isolated, Path(real_user_data))
            (isolated / "auto_save" / "probe").mkdir(parents=True)
            (isolated / ".pyside_bdo_gui.json").write_text(
                "{}",
                encoding="utf-8",
            )
            return 0

        with (
            patch.dict(
                os.environ,
                {
                    "BDO_USER_DATA_DIR": real_user_data,
                    "QT_QPA_PLATFORM": "windows",
                    "BDO_STARTUP_SELF_TEST": "outer",
                },
            ),
            patch.object(
                application_entry,
                "_run_startup_self_test_gui",
                side_effect=probe,
            ) as gui_probe,
        ):
            self.assertEqual(application_entry._self_test_startup(), 0)
            self.assertEqual(os.environ["BDO_USER_DATA_DIR"], real_user_data)
            self.assertEqual(os.environ["QT_QPA_PLATFORM"], "windows")
            self.assertEqual(os.environ["BDO_STARTUP_SELF_TEST"], "outer")

        gui_probe.assert_called_once_with()
        self.assertEqual(observed["platform"], "offscreen")
        self.assertEqual(observed["self_test"], "1")
        self.assertFalse(Path(observed["path"]).exists())

    def test_source_startup_probe_routes_writes_to_isolated_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            isolated = Path(directory) / "self-test-user-data"
            environment = dict(os.environ)
            environment.update(
                {
                    "BDO_USER_DATA_DIR": str(isolated),
                    "BDO_STARTUP_SELF_TEST": "1",
                    "QT_QPA_PLATFORM": "offscreen",
                }
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "from pathlib import Path; import pyside_bdo_gui as gui; "
                        "assert gui.WRITABLE_ROOT == "
                        "Path(r'" + str(isolated) + "')"
                    ),
                ],
                cwd=PROJECT_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(
                completed.returncode,
                0,
                completed.stdout + completed.stderr,
            )

    @unittest.skipUnless(
        all(
            importlib.util.find_spec(name) is not None
            for name in (
                "basic_pitch",
                "onnxruntime",
                "soundfile",
                "soxr",
            )
        ),
        "transcription runtime is not installed",
    )
    def test_source_transcription_self_test_runs_synthetic_inference(
        self,
    ) -> None:
        self.assertEqual(application_entry._self_test_transcription(), 0)


if __name__ == "__main__":
    unittest.main()
