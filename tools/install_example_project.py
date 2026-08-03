#!/usr/bin/env python3
"""Install a private, sanitized project as a local homepage example.

The command never writes the source project or MIDI into repository assets.
It is intended for maintainers/users who have a lawful local copy and want an
example on their own machine.  Redistribution rights are deliberately outside
this utility's scope.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bdo_music_composer.core.project_paths import USER_DATA_DIR


EXAMPLE_METADATA_VERSION = 1


def sanitize_example_payload(
    payload: dict,
    *,
    example_id: str,
    title: str,
    source_name: str,
) -> dict:
    """Return a project payload without owner, character, or machine paths."""

    sanitized = json.loads(json.dumps(payload, ensure_ascii=False))
    sanitized["original_midi_path"] = ""
    sanitized["source_midi_path"] = "source.mid"
    sanitized["reference_audio_path"] = ""
    sanitized["reference_audio_attached"] = False
    sanitized["owner_id"] = 0
    sanitized["char_name"] = "MIDI"
    sanitized["output_name"] = str(title).strip()
    sanitized["saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    sanitized["reason"] = "local example install"
    # Imported lyric metadata can contain identity/copyright text and the
    # historical fixture also has a broken source encoding.  The example is
    # intentionally an arrangement/editing demonstration only.
    sanitized["lyric_events"] = []
    conversion = sanitized.get("conversion_settings")
    if isinstance(conversion, dict):
        conversion["char_name"] = "MIDI"
    sanitized["transcription_review"] = {}
    sanitized["transcription_assist_review"] = {}
    research = sanitized.get("research")
    if not isinstance(research, dict):
        research = {}
        sanitized["research"] = research
    research["local_example"] = {
        "version": EXAMPLE_METADATA_VERSION,
        "id": str(example_id).strip(),
        "source": str(source_name).strip(),
        "redistribution_verified": False,
    }
    return sanitized


def install_example_project(
    project_path: Path,
    *,
    destination_root: Path,
    example_id: str,
    title: str,
    source_name: str,
    replace: bool = False,
) -> Path:
    source_project = Path(project_path).resolve()
    if not source_project.is_file() or source_project.name != "project.json":
        raise ValueError("source must be an existing project.json")
    payload = json.loads(source_project.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("tracks"), list):
        raise ValueError("source project payload is invalid")
    midi_reference = str(payload.get("source_midi_path") or "").strip()
    source_midi = source_project.parent / midi_reference
    if not midi_reference or Path(midi_reference).is_absolute() or not source_midi.is_file():
        raise ValueError("source project has no safe project-relative MIDI")

    destination = Path(destination_root) / str(example_id).strip()
    if destination.exists() and not replace:
        raise FileExistsError("local example already exists")
    destination.mkdir(parents=True, exist_ok=True)
    sanitized = sanitize_example_payload(
        payload,
        example_id=example_id,
        title=title,
        source_name=source_name,
    )
    project_target = destination / "project.json"
    temporary_target = destination / "project.json.tmp"
    temporary_target.write_text(
        json.dumps(sanitized, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    midi_temporary = destination / "source.mid.tmp"
    shutil.copy2(source_midi, midi_temporary)
    midi_temporary.replace(destination / "source.mid")
    temporary_target.replace(project_target)
    manifest = {
        "version": EXAMPLE_METADATA_VERSION,
        "id": str(example_id).strip(),
        "title": str(title).strip(),
        "source": str(source_name).strip(),
        "project": "project.json",
        "redistribution_verified": False,
    }
    manifest_temporary = destination / "example.json.tmp"
    manifest_temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    manifest_temporary.replace(destination / "example.json")
    return project_target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("--destination", type=Path, default=USER_DATA_DIR / "examples")
    parser.add_argument("--id", default="gold-rush-town")
    parser.add_argument("--title", default="淘金小镇 · 示例")
    parser.add_argument("--source", default="MidiShow")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args(argv)
    installed = install_example_project(
        args.project,
        destination_root=args.destination,
        example_id=args.id,
        title=args.title,
        source_name=args.source,
        replace=args.replace,
    )
    print(installed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
