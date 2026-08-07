from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

from bdo_music_composer.app.application_metadata import APP_VERSION
from bdo_music_composer.sdk.core_api import (
    SDK_API_VERSION,
    Note,
    TrackState,
    build_score_document,
    decode_score,
    encode_score,
)
ROOT = Path(__file__).resolve().parents[1]
_BUILDER_SPEC = importlib.util.spec_from_file_location(
    "bdo_developer_sdk_builder",
    ROOT / "packaging/developer_sdk/build_sdk.py",
)
assert _BUILDER_SPEC is not None and _BUILDER_SPEC.loader is not None
_BUILDER = importlib.util.module_from_spec(_BUILDER_SPEC)
sys.modules[_BUILDER_SPEC.name] = _BUILDER
_BUILDER_SPEC.loader.exec_module(_BUILDER)
ARCHIVE_PREFIX = _BUILDER.ARCHIVE_PREFIX
build_sdk = _BUILDER.build_sdk


class DeveloperSdkCoreTests(unittest.TestCase):
    def test_core_and_ui_module_imports_are_qt_lazy(self) -> None:
        command = (
            "import sys; "
            "import bdo_music_composer.sdk.core_api; "
            "import bdo_music_composer.sdk.ui_api; "
            "assert not any(name == 'PySide6' or name.startswith('PySide6.') "
            "for name in sys.modules)"
        )
        subprocess.run(
            [sys.executable, "-c", command],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_core_api_builds_and_decodes_canonical_document(self) -> None:
        notes = [[
            Note(60, 87, 0.0, 400.0, 0),
            Note(64, 99, 500.0, 450.0, 4),
        ]]
        document = build_score_document(
            bpm=120,
            time_sig_num=4,
            instrument_groups=[(0, notes)],
            char_name="SDK",
            owner_id=0,
        )
        decoded = decode_score(encode_score(document))
        self.assertEqual(decoded.header.bpm, 120)
        self.assertEqual(decoded.total_notes, 2)
        self.assertEqual(decoded.groups[0].tracks[0].notes[1].ntype, 4)
        self.assertGreaterEqual(SDK_API_VERSION, 1)

    def test_public_editor_model_keeps_note_wire_shape(self) -> None:
        note = Note(60, 100, 25.0, 500.0, 0)
        track = TrackState(1, [note], 0, False, "Piano", 0)
        self.assertEqual(tuple(note), (60, 100, 25.0, 500.0, 0))
        self.assertEqual(track.note_count, 1)
        self.assertEqual(track.end_ms, 525.0)


class DeveloperSdkArchiveTests(unittest.TestCase):
    def test_archive_is_deterministic_and_manifest_is_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            first = build_sdk(temporary / "first.zip")
            second = build_sdk(temporary / "second.zip")
            self.assertEqual(sha256(first.read_bytes()).digest(), sha256(second.read_bytes()).digest())

            with ZipFile(first) as archive:
                names = archive.namelist()
                prefix = f"{ARCHIVE_PREFIX}/"
                required = {
                    f"{prefix}SDK_MANIFEST.json",
                    f"{prefix}SDK_README.md",
                    f"{prefix}pyproject.toml",
                    f"{prefix}bdo_music_composer/sdk/core_api.py",
                    f"{prefix}bdo_music_composer/sdk/ui_api.py",
                    f"{prefix}docs/DEVELOPER_SDK.md",
                    f"{prefix}examples/sdk/timeline_widget.py",
                }
                self.assertTrue(required.issubset(names))
                forbidden_suffixes = {
                    ".bdo", ".mid", ".midi", ".wav", ".wem", ".bnk",
                    ".exe", ".zip",
                }
                for name in names:
                    relative = PurePosixPath(name.removeprefix(prefix))
                    self.assertFalse({part.lower() for part in relative.parts} & {
                        ".git", ".venv", "auto_save", "build", "dist", "out", "releases",
                    })
                    self.assertNotIn(relative.suffix.lower(), forbidden_suffixes)
                    self.assertNotEqual(relative.name.lower(), "release_notes.json")

                manifest = json.loads(archive.read(f"{prefix}SDK_MANIFEST.json"))
                self.assertEqual(manifest["application_version"], APP_VERSION)
                self.assertEqual(manifest["sdk_api_version"], SDK_API_VERSION)
                for item in manifest["files"]:
                    data = archive.read(f"{prefix}{item['path']}")
                    self.assertEqual(len(data), item["size"])
                    self.assertEqual(sha256(data).hexdigest(), item["sha256"])


class DeveloperSdkUiSmokeTests(unittest.TestCase):
    def test_standalone_timeline_can_render(self) -> None:
        command = "\n".join((
            "from bdo_music_composer.sdk.core_api import Note, TrackState",
            "from bdo_music_composer.sdk.ui_api import create_application, create_timeline_canvas",
            "app = create_application(['sdk-ui-test'], language='zh_CN')",
            "track = TrackState(1, [Note(60, 90, 0.0, 500.0, 0)], 0, False, 'SDK', 0)",
            "canvas = create_timeline_canvas([track])",
            "canvas.resize(640, 360)",
            "image = canvas.grab().toImage()",
            "assert not image.isNull()",
            "assert len(canvas.tracks) == 1",
            "canvas.close()",
        ))
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [sys.executable, "-c", command],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0 and "No module named 'PySide6'" in completed.stderr:
            self.skipTest("PySide6 is not installed")
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
