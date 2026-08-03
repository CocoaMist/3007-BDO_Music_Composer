from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from bdo_music_composer.ui.main_window import scan_example_projects
from tools.install_example_project import install_example_project


class ExampleProjectTests(unittest.TestCase):
    def test_local_install_is_sanitized_attributed_and_home_scannable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source-project"
            source.mkdir()
            (source / "source.mid").write_bytes(b"MThd-local-fixture")
            payload = {
                "schema_version": 8,
                "path_policy": "project-relative-v1",
                "source_midi_path": "source.mid",
                "original_midi_path": "C:/private/source.mid",
                "reference_audio_path": "C:/private/reference.wav",
                "reference_audio_attached": True,
                "owner_id": 123456,
                "char_name": "Private Character",
                "output_name": "private",
                "lyric_events": [{"kind": "lyrics", "text": "private"}],
                "conversion_settings": {"char_name": "Private Character"},
                "transcription_review": {"cache_key": "private"},
                "transcription_assist_review": {"audio_fingerprint": "private"},
                "tracks": [{"track_id": 1, "notes": []}],
                "research": {},
            }
            project = source / "project.json"
            project.write_text(json.dumps(payload), encoding="utf-8")
            examples = root / "examples"

            installed = install_example_project(
                project,
                destination_root=examples,
                example_id="gold-rush-town",
                title="淘金小镇 · 示例",
                source_name="MidiShow",
            )
            result = json.loads(installed.read_text(encoding="utf-8"))
            self.assertEqual(0, result["owner_id"])
            self.assertEqual("MIDI", result["char_name"])
            self.assertEqual([], result["lyric_events"])
            self.assertEqual("", result["reference_audio_path"])
            self.assertFalse(result["reference_audio_attached"])
            self.assertEqual("source.mid", result["source_midi_path"])
            self.assertEqual(
                b"MThd-local-fixture",
                installed.with_name("source.mid").read_bytes(),
            )
            self.assertFalse(
                result["research"]["local_example"]["redistribution_verified"]
            )

            entries = scan_example_projects(examples)
            self.assertEqual(1, len(entries))
            self.assertEqual("example", entries[0].kind)
            self.assertEqual("淘金小镇 · 示例", entries[0].label)
            self.assertEqual("示例 · 来源：MidiShow", entries[0].detail)
            self.assertEqual(installed, entries[0].path)

    def test_manifest_traversal_and_oversized_metadata_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bad = root / "bad"
            bad.mkdir()
            (bad / "project.json").write_text("{}", encoding="utf-8")
            (bad / "example.json").write_text(
                json.dumps({"project": "../project.json"}),
                encoding="utf-8",
            )
            self.assertEqual([], scan_example_projects(root))
            (bad / "example.json").write_bytes(b" " * (64 * 1024 + 1))
            self.assertEqual([], scan_example_projects(root))


if __name__ == "__main__":
    unittest.main()
