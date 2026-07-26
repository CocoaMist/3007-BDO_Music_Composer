"""Local-only BDO sample packs; game audio is never bundled with the app."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from typing import Callable
import zipfile


PACK_FORMAT = 1
PACK_SUFFIX = ".bdosamples"
MANIFEST_NAME = "manifest.json"


class SamplePackError(ValueError):
    pass


class SamplePackCancelled(Exception):
    pass


ProgressCallback = Callable[[int], None]
CancelCallback = Callable[[], bool]


def _cancel_if_requested(cancelled: CancelCallback | None) -> None:
    if cancelled is not None and cancelled():
        raise SamplePackCancelled("sample-pack preparation cancelled")


def _sha256(
    path: Path,
    *,
    progress: ProgressCallback | None = None,
    progress_start: int = 0,
    progress_span: int = 100,
    cancelled: CancelCallback | None = None,
) -> str:
    digest = hashlib.sha256()
    total = max(1, path.stat().st_size)
    completed = 0
    with path.open("rb") as source:
        while True:
            _cancel_if_requested(cancelled)
            block = source.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
            completed += len(block)
            if progress is not None:
                progress(
                    min(
                        progress_start + progress_span,
                        progress_start
                        + round(progress_span * completed / total),
                    )
                )
    _cancel_if_requested(cancelled)
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


def _ready_sample_cache(target: Path, pack_hash: str) -> bool:
    if target.is_symlink() or not target.is_dir():
        return False
    ready = target / ".ready"
    try:
        return (
            not ready.is_symlink()
            and ready.is_file()
            and ready.read_text(encoding="ascii").strip() == pack_hash
        )
    except (OSError, UnicodeError):
        return False


def extract_sample_pack(
    pack_path: Path,
    cache_root: Path,
    *,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> Path:
    """Validate and extract a pack to a deterministic local cache directory."""
    if not pack_path.is_file():
        raise SamplePackError(f"sample pack not found: {pack_path}")
    if progress is not None:
        progress(0)
    pack_hash = _sha256(
        pack_path,
        progress=progress,
        progress_start=0,
        progress_span=20,
        cancelled=cancelled,
    )
    target = cache_root / pack_hash[:16]
    if _ready_sample_cache(target, pack_hash):
        if progress is not None:
            progress(100)
        return target
    if target.exists() or target.is_symlink():
        raise SamplePackError("sample-pack cache target exists but is invalid")
    cache_root.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{pack_hash[:16]}.tmp-",
            dir=cache_root,
        )
    )
    try:
        with zipfile.ZipFile(pack_path) as archive:
            try:
                manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SamplePackError("invalid sample-pack manifest") from exc
            if manifest.get("format") != PACK_FORMAT or not isinstance(manifest.get("files"), list):
                raise SamplePackError("unsupported sample-pack format")
            names = set(archive.namelist())
            records = manifest["files"]
            record_count = max(1, len(records))
            for index, record in enumerate(records):
                _cancel_if_requested(cancelled)
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
                    while True:
                        _cancel_if_requested(cancelled)
                        block = source.read(1024 * 1024)
                        if not block:
                            break
                        digest.update(block)
                        output.write(block)
                if destination.stat().st_size != int(record.get("size", -1)) or digest.hexdigest() != record.get("sha256"):
                    raise SamplePackError(f"sample verification failed: {name}")
                if progress is not None:
                    progress(20 + round(79 * (index + 1) / record_count))
        _cancel_if_requested(cancelled)
        # The source can be replaced while ZipFile is reading it.  Never
        # publish evidence under the digest of different bytes.
        if _sha256(pack_path, cancelled=cancelled) != pack_hash:
            raise SamplePackError("sample pack changed while being prepared")
        (staging / ".ready").write_text(pack_hash, encoding="ascii")
        try:
            staging.replace(target)
        except OSError as exc:
            # Another process may have atomically published the same complete
            # cache first.  Its ready marker must bind to the exact digest.
            if _ready_sample_cache(target, pack_hash):
                if staging.exists():
                    shutil.rmtree(staging)
            else:
                raise SamplePackError(
                    "sample-pack cache publish conflict"
                ) from exc
        if progress is not None:
            progress(100)
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
