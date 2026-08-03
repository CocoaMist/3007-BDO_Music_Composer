"""Crash-safe atomic writes for user-owned project and score files."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Mapping, Any


def _temporary_path(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    os.close(descriptor)
    return Path(raw_path)


def atomic_write_bytes(path: str | Path, data: bytes) -> None:
    """Replace *path* only after all bytes have reached a temporary file."""

    target = Path(path)
    temporary = _temporary_path(target)
    try:
        with temporary.open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    """Stream compact UTF-8 JSON to a temporary file, then replace atomically."""

    target = Path(path)
    temporary = _temporary_path(target)
    try:
        with temporary.open("w", encoding="utf-8", newline="") as stream:
            json.dump(
                payload,
                stream,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_copy_file(source: str | Path, destination: str | Path) -> Path:
    """Copy a file without exposing a partially overwritten destination."""

    source_path = Path(source)
    target = Path(destination)
    try:
        if source_path.resolve() == target.resolve():
            return target
    except OSError:
        pass
    temporary = _temporary_path(target)
    try:
        shutil.copy2(source_path, temporary)
        with temporary.open("rb+") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


__all__ = ["atomic_copy_file", "atomic_write_bytes", "atomic_write_json"]
