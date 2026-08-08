#!/usr/bin/env python3
"""Generate and sign one dual-mirror self-update channel document."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bdo_music_composer.app.application_metadata import (
    UPDATE_APP_ID,
    UPDATE_CHANNEL,
    UPDATE_PROTOCOL_VERSION,
)
from bdo_music_composer.app.update_check import SemanticVersion
from bdo_music_composer.update.install import file_sha256
from bdo_music_composer.update.manifest import parse_signed_manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--github-url", required=True)
    parser.add_argument("--gitee-url", required=True)
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--openssl", default="openssl")
    parser.add_argument("--notes-zh", default="")
    parser.add_argument("--notes-en", default="")
    parser.add_argument("--mandatory", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    executable = args.executable.resolve(strict=True)
    private_key = args.private_key.resolve(strict=True)
    version = SemanticVersion.parse(args.version)
    if version.prerelease:
        raise SystemExit("stable update manifests cannot use a prerelease version")
    digest = file_sha256(executable)
    notes = {"zh_CN": args.notes_zh}
    if args.notes_en:
        notes["en_US"] = args.notes_en
    payload = {
        "schema_version": 1,
        "app_id": UPDATE_APP_ID,
        "channel": UPDATE_CHANNEL,
        "version": str(version),
        "published_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "update_protocol": UPDATE_PROTOCOL_VERSION,
        "mandatory": bool(args.mandatory),
        "release_notes": notes,
        "artifacts": [{
            "platform": "windows",
            "architecture": "x86_64",
            "type": "pyinstaller-onefile",
            "filename": "BDO-Music-Composer.exe",
            "size": executable.stat().st_size,
            "sha256": digest,
            "urls": {
                "github": args.github_url,
                "gitee": args.gitee_url,
            },
        }],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "update-manifest-v1.json"
    raw_signature_path = output_dir / ".update-manifest-v1.sig.raw"
    signature_path = output_dir / "update-manifest-v1.json.sig"
    manifest_path.write_bytes(encoded)
    openssl = shutil.which(args.openssl) or args.openssl
    try:
        subprocess.run(
            [
                str(openssl),
                "dgst",
                "-sha256",
                "-sign",
                str(private_key),
                "-out",
                str(raw_signature_path),
                str(manifest_path),
            ],
            check=True,
        )
        signature_path.write_bytes(
            base64.b64encode(raw_signature_path.read_bytes()) + b"\n"
        )
    finally:
        raw_signature_path.unlink(missing_ok=True)
    # Fail closed if the operator selected a key that does not match the public
    # trust root embedded in the application.
    parsed = parse_signed_manifest(encoded, signature_path.read_bytes())
    if parsed.version != version or parsed.artifact.sha256 != digest:
        raise SystemExit("generated update manifest failed self-verification")
    print(manifest_path)
    print(signature_path)
    print(f"sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
