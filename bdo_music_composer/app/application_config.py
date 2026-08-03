"""Crash-safe application-package persistence for global preferences.

Configuration remains intentionally schema-free at this boundary.  Callers
may add fields without teaching this module about them, and a loaded mapping
can therefore be edited and saved without discarding newer or optional keys.
"""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Mapping

from bdo_common.atomic_io import atomic_copy_file, atomic_write_bytes


def load_config(path: str | Path) -> dict[str, Any]:
    """Load one JSON object, returning an empty mapping when it is unusable.

    Loading is read-only.  A corrupt file is retained in place so a later
    :func:`save_config` call can preserve its exact bytes as a recovery copy.
    """

    config_path = Path(path)
    if not config_path.exists():
        return {}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("configuration root must be an object")
        return payload
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return {}


def _corrupt_backup_path(config_path: Path) -> Path:
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    backup = config_path.with_name(
        f"{config_path.stem}.corrupt-{timestamp}{config_path.suffix}"
    )
    suffix = 2
    while backup.exists():
        backup = config_path.with_name(
            f"{config_path.stem}.corrupt-{timestamp}-{suffix}"
            f"{config_path.suffix}"
        )
        suffix += 1
    return backup


def save_config(path: str | Path, payload: Mapping[str, Any]) -> None:
    """Atomically replace a configuration object at *path*.

    If the existing file is not a valid JSON object, its exact bytes are first
    copied to a uniquely named ``*.corrupt-<timestamp>*`` recovery file.  The
    shared atomic-I/O layer creates missing parent directories and guarantees
    that a failed replacement leaves the previous destination intact.
    """

    if not isinstance(payload, Mapping):
        raise TypeError("configuration root must be a mapping")

    config_path = Path(path)
    if config_path.is_file():
        try:
            existing = json.loads(config_path.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                raise ValueError("configuration root must be an object")
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            atomic_copy_file(config_path, _corrupt_backup_path(config_path))

    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    atomic_write_bytes(config_path, encoded)


def safe_filename(value: str, fallback: str = "project") -> str:
    """Return a bounded Windows-safe filename component.

    Invalid and control characters become underscores.  Windows-trimmed edge
    characters are removed and an empty result uses the caller's fallback.
    """

    cleaned = "".join(
        character
        if character not in '<>:"/\\|?*' and ord(character) >= 32
        else "_"
        for character in value
    ).strip(" ._")
    return cleaned[:80] or fallback


__all__ = ["load_config", "safe_filename", "save_config"]
