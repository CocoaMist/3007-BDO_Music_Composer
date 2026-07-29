import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import atomic_io


class AtomicIoTests(unittest.TestCase):
    def test_failed_replace_preserves_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "score.bdo"
            target.write_bytes(b"known-good")
            with patch.object(atomic_io.os, "replace", side_effect=OSError("busy")):
                with self.assertRaises(OSError):
                    atomic_io.atomic_write_bytes(target, b"replacement")
            self.assertEqual(target.read_bytes(), b"known-good")
            self.assertEqual(list(target.parent.glob(f".{target.name}.*.tmp")), [])

    def test_atomic_copy_tolerates_same_source_and_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "score.bdo"
            target.write_bytes(b"score")
            self.assertEqual(atomic_io.atomic_copy_file(target, target), target)
            self.assertEqual(target.read_bytes(), b"score")

    def test_atomic_json_successfully_replaces_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "nested" / "project.json"
            atomic_io.atomic_write_json(target, {"title": "曲谱", "version": 1})
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                '{"title":"曲谱","version":1}',
            )

    def test_failed_json_replace_preserves_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "project.json"
            target.write_text("known-good", encoding="utf-8")
            with patch.object(atomic_io.os, "replace", side_effect=OSError("busy")):
                with self.assertRaises(OSError):
                    atomic_io.atomic_write_json(target, {"replacement": True})
            self.assertEqual(target.read_text(encoding="utf-8"), "known-good")
            self.assertEqual(list(target.parent.glob(f".{target.name}.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
