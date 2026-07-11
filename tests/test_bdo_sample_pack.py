from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import wave
import zipfile

from bdo_sample_pack import SamplePackError, create_sample_pack, extract_sample_pack


class SamplePackTests(unittest.TestCase):
    def _sample_tree(self, root: Path) -> Path:
        sample = root / "audio" / "乐器_WAV" / "midi_instrument_00_acousticguitar" / "123.wav"
        sample.parent.mkdir(parents=True)
        with wave.open(str(sample), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(48_000)
            output.writeframes(b"\x00\x00" * 32)
        return sample

    def test_pack_round_trip_and_cache_reuse(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._sample_tree(root)
            pack = root / "samples.bdosamples"
            manifest = create_sample_pack(source.parents[2], pack)
            self.assertEqual(len(manifest["files"]), 1)
            extracted = extract_sample_pack(pack, root / "cache")
            restored = extracted / manifest["files"][0]["path"]
            self.assertEqual(restored.read_bytes(), source.read_bytes())
            self.assertEqual(extract_sample_pack(pack, root / "cache"), extracted)

    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pack = root / "unsafe.bdosamples"
            manifest = {"format": 1, "files": [{"path": "../escape.wav", "size": 0, "sha256": ""}]}
            with zipfile.ZipFile(pack, "w") as archive:
                archive.writestr("manifest.json", json.dumps(manifest))
                archive.writestr("../escape.wav", b"")
            with self.assertRaises(SamplePackError):
                extract_sample_pack(pack, root / "cache")
            self.assertFalse((root / "escape.wav").exists())


if __name__ == "__main__":
    unittest.main()
