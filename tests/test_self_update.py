from __future__ import annotations

import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bdo_music_composer.update.install import (
    STATE_NAME,
    UpdateInstallError,
    apply_update_plan,
    create_install_plan,
    file_sha256,
)
from bdo_music_composer.update.manifest import (
    ManifestError,
    ManifestErrorCode,
    _parse_manifest_payload,
    verify_manifest_signature,
)
from bdo_music_composer.update.preferences import update_preferences


_SIGNATURE_FIXTURE = (
    "GwC2J1Y1DzVS52B2j0IptHUuAPOP25JfALZteg5RHXRd3r2SYaePJr9cx1OEUDHQ"
    "26lYWxz8XQH3qtUOUNoeEu8+B/9/ltOudls9nbQ5qqFIruFc/UVk8dLTzlEctyjZ7"
    "YnLp3Dl4rt37u6B8StfOYW+XKgWwMtpO477Hw9K86hLljIZv/LytBwhiUuxJpjAi"
    "He74UTztExtOXoT/MiDOijVwVz01B4o4Pyj+LpC/PTFuuiO4C1q6rp5IhtDWfec0U"
    "WfkpcLkoAGEXu7gLmk/fhH97XYcuk8NuMznEsvEVOZFHrsfYWvlFlWmANBFpAmGw"
    "Ce4/VAbq1U6CXt/D+HVDaw0jHmozrqN4STx4FuBucbsSHb6lchj/qyZCRCvmzusBE"
    "WQsLZGl0fyG9+WRIv9m/67C44M2W0+3eoIwL17Odnb9hk8S7LLTASz0S4840P3hL"
    "v8Esio/elA9xiidGvHEjad6qKYQO43zN24OIyOvuVElLAXGVeoMnjGT3PlJhF"
)


def _manifest_payload(**changes: object) -> bytes:
    payload: dict[str, object] = {
        "schema_version": 1,
        "app_id": "CocoaMist.BDOMusicComposer",
        "channel": "stable",
        "version": "1.2.0.1",
        "published_at": "2026-08-08T12:00:00Z",
        "update_protocol": 1,
        "mandatory": False,
        "release_notes": {
            "zh_CN": "测试更新",
            "en_US": "Test update",
        },
        "artifacts": [{
            "platform": "windows",
            "architecture": "x86_64",
            "type": "pyinstaller-onefile",
            "filename": "BDO-Music-Composer.exe",
            "size": 123,
            "sha256": "a" * 64,
            "urls": {
                "github": "https://github.com/CocoaMist/repo/releases/download/v1.2.0.1/BDO-Music-Composer.exe",
                "gitee": "https://gitee.com/CocoaMist/repo/releases/download/v1.2.0.1/BDO-Music-Composer.exe",
            },
        }],
    }
    payload.update(changes)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class SignedManifestTests(unittest.TestCase):
    def test_embedded_release_key_accepts_known_signature(self) -> None:
        verify_manifest_signature(
            b"manifest signature fixture\n",
            _SIGNATURE_FIXTURE,
        )

    def test_signature_rejects_changed_payload_and_signature(self) -> None:
        with self.assertRaisesRegex(ManifestError, "invalid_signature"):
            verify_manifest_signature(b"manifest signature fixture", _SIGNATURE_FIXTURE)
        damaged = bytearray(base64.b64decode(_SIGNATURE_FIXTURE))
        damaged[-1] ^= 1
        with self.assertRaisesRegex(ManifestError, "invalid_signature"):
            verify_manifest_signature(
                b"manifest signature fixture\n",
                base64.b64encode(damaged),
            )

    def test_strict_manifest_selects_the_windows_onefile_artifact(self) -> None:
        manifest = _parse_manifest_payload(_manifest_payload())
        self.assertEqual("1.2.0.1", str(manifest.version))
        self.assertEqual("BDO-Music-Composer.exe", manifest.artifact.filename)
        self.assertEqual("https", manifest.artifact.url_for("gitee").split(":", 1)[0])
        self.assertEqual("测试更新", manifest.localized_notes("zh_TW"))
        self.assertEqual("Test update", manifest.localized_notes("ja_JP"))

    def test_manifest_rejects_untrusted_download_host_and_unknown_fields(self) -> None:
        payload = json.loads(_manifest_payload())
        payload["artifacts"][0]["urls"]["github"] = "https://attacker.example/update.exe"
        with self.assertRaisesRegex(ManifestError, "invalid_schema"):
            _parse_manifest_payload(json.dumps(payload).encode())
        payload = json.loads(_manifest_payload())
        payload["unexpected"] = True
        with self.assertRaisesRegex(ManifestError, "invalid_schema"):
            _parse_manifest_payload(json.dumps(payload).encode())

    def test_manifest_rejects_prerelease_protocol_and_bad_digest(self) -> None:
        for changes, code in (
            ({"version": "1.2.0-rc.1"}, ManifestErrorCode.INVALID_SCHEMA),
            ({"update_protocol": 2}, ManifestErrorCode.UNSUPPORTED_PROTOCOL),
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(ManifestError) as caught:
                    _parse_manifest_payload(_manifest_payload(**changes))
                self.assertEqual(code, caught.exception.code)


class UpdateInstallTests(unittest.TestCase):
    def test_staged_executable_replaces_target_and_keeps_recovery_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target_dir = root / "installed"
            staged_dir = root / "updates" / "1.2.0"
            target_dir.mkdir(parents=True)
            staged_dir.mkdir(parents=True)
            target = target_dir / "BDO-Music-Composer.exe"
            staged = staged_dir / "BDO-Music-Composer.exe"
            target.write_bytes(b"old executable")
            staged.write_bytes(b"new executable")
            plan_path, token = create_install_plan(
                staged,
                version="1.2.0",
                sha256=file_sha256(staged),
                target_executable=target,
                parent_pid=0,
            )
            self.assertEqual(
                0,
                apply_update_plan(
                    plan_path,
                    token,
                    running_executable=staged,
                    launch=False,
                ),
            )
            self.assertEqual(b"new executable", target.read_bytes())
            self.assertEqual(
                b"old executable",
                target.with_suffix(".exe.old").read_bytes(),
            )
            state = json.loads((staged_dir / STATE_NAME).read_text(encoding="utf-8"))
            self.assertEqual("installed", state["status"])

    def test_plan_rejects_tampering_and_wrong_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target_dir = root / "installed"
            staged_dir = root / "updates"
            target_dir.mkdir()
            staged_dir.mkdir()
            target = target_dir / "BDO-Music-Composer.exe"
            staged = staged_dir / "BDO-Music-Composer.exe"
            target.write_bytes(b"old")
            staged.write_bytes(b"new")
            plan_path, token = create_install_plan(
                staged,
                version="1.2.0",
                sha256=file_sha256(staged),
                target_executable=target,
                parent_pid=0,
            )
            with self.assertRaises(UpdateInstallError):
                apply_update_plan(
                    plan_path,
                    "wrong-token",
                    running_executable=staged,
                    launch=False,
                )
            staged.write_bytes(b"tampered")
            with self.assertRaises(UpdateInstallError):
                apply_update_plan(
                    plan_path,
                    token,
                    running_executable=staged,
                    launch=False,
                )

    def test_launch_failure_rolls_back_before_returning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target_dir = root / "installed"
            staged_dir = root / "updates"
            target_dir.mkdir()
            staged_dir.mkdir()
            target = target_dir / "BDO-Music-Composer.exe"
            staged = staged_dir / "BDO-Music-Composer.exe"
            target.write_bytes(b"known-good old executable")
            staged.write_bytes(b"new executable")
            plan_path, token = create_install_plan(
                staged,
                version="1.2.0",
                sha256=file_sha256(staged),
                target_executable=target,
                parent_pid=0,
            )
            with patch(
                "bdo_music_composer.update.install.subprocess.Popen",
                side_effect=OSError("launch failed"),
            ):
                result = apply_update_plan(
                    plan_path,
                    token,
                    running_executable=staged,
                    launch=True,
                )
            self.assertEqual(2, result)
            self.assertEqual(b"known-good old executable", target.read_bytes())
            self.assertFalse(target.with_suffix(".exe.old").exists())

    def test_unwritable_target_failure_keeps_old_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target_dir = root / "installed"
            staged_dir = root / "updates"
            target_dir.mkdir()
            staged_dir.mkdir()
            target = target_dir / "BDO-Music-Composer.exe"
            staged = staged_dir / "BDO-Music-Composer.exe"
            target.write_bytes(b"old executable")
            staged.write_bytes(b"new executable")
            plan_path, token = create_install_plan(
                staged,
                version="1.2.0",
                sha256=file_sha256(staged),
                target_executable=target,
                parent_pid=0,
            )
            with (
                patch(
                    "bdo_music_composer.update.install.shutil.copy2",
                    side_effect=PermissionError("read only"),
                ),
                patch("bdo_music_composer.update.install.subprocess.Popen"),
            ):
                result = apply_update_plan(
                    plan_path,
                    token,
                    running_executable=staged,
                    launch=True,
                )
            self.assertEqual(2, result)
            self.assertEqual(b"old executable", target.read_bytes())


class UpdatePreferenceTests(unittest.TestCase):
    def test_defaults_enable_seamless_updates_and_invalid_values_fail_safe(self) -> None:
        self.assertEqual(
            {
                "enabled": True,
                "auto_download": True,
                "source": "auto",
                "highest_version": "",
                "last_source": "",
                "last_check": 0,
            },
            update_preferences({}),
        )
        normalized = update_preferences({
            "updates": {
                "enabled": False,
                "source": "attacker",
                "last_source": "attacker",
                "last_check": "now",
            }
        })
        self.assertFalse(normalized["enabled"])
        self.assertEqual("auto", normalized["source"])
        self.assertEqual(0, normalized["last_check"])


if __name__ == "__main__":
    unittest.main()
