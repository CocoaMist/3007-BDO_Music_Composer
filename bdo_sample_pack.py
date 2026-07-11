"""Local-only BDO sample packs; game audio is never bundled with the app."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import zipfile


PACK_FORMAT = 1
PACK_SUFFIX = ".bdosamples"
MANIFEST_NAME = "manifest.json"


class SamplePackError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def create_sample_pack(audio_root: Path, output_path: Path) -> dict:
    """Pack a user-owned ``乐器_WAV`` tree into one local archive."""
    wav_root = audio_root / "乐器_WAV"
    if not wav_root.is_dir():
        raise SamplePackError(f"missing sample directory: {wav_root}")
    files = sorted(path for path in wav_root.rglob("*.wav") if path.is_file())
    if not files:
        raise SamplePackError("no WAV samples found")
    manifest = {
        "format": PACK_FORMAT,
        "notice": "User-created local pack. No game audio is distributed with BDO Music Composer.",
        "files": [
            {
                "path": (PurePosixPath("乐器_WAV") / path.relative_to(wav_root).as_posix()).as_posix(),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in files
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
        for path, record in zip(files, manifest["files"], strict=True):
            archive.write(path, record["path"])
    return manifest


def extract_sample_pack(pack_path: Path, cache_root: Path) -> Path:
    """Validate and extract a pack to a deterministic local cache directory."""
    if not pack_path.is_file():
        raise SamplePackError(f"sample pack not found: {pack_path}")
    pack_hash = _sha256(pack_path)
    target = cache_root / pack_hash[:16]
    ready = target / ".ready"
    if ready.is_file():
        return target
    staging = cache_root / f".{pack_hash[:16]}.tmp"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(pack_path) as archive:
            try:
                manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SamplePackError("invalid sample-pack manifest") from exc
            if manifest.get("format") != PACK_FORMAT or not isinstance(manifest.get("files"), list):
                raise SamplePackError("unsupported sample-pack format")
            names = set(archive.namelist())
            for record in manifest["files"]:
                relative = PurePosixPath(str(record.get("path", "")))
                if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".wav":
                    raise SamplePackError(f"unsafe sample-pack path: {relative}")
                name = relative.as_posix()
                if name not in names:
                    raise SamplePackError(f"missing packed sample: {name}")
                destination = staging.joinpath(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                with archive.open(name) as source, destination.open("wb") as output:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(block)
                        output.write(block)
                if destination.stat().st_size != int(record.get("size", -1)) or digest.hexdigest() != record.get("sha256"):
                    raise SamplePackError(f"sample verification failed: {name}")
        cache_root.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        staging.replace(target)
        ready.write_text(pack_hash, encoding="ascii")
        return target
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a local .bdosamples archive from user-owned WAV files.")
    parser.add_argument("audio_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    create_sample_pack(args.audio_root, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
