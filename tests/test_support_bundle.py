from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from bdo_music_composer.app import crash_logging, support_bundle


class SupportBundleTests(unittest.TestCase):
    def test_bundle_is_bounded_redacted_and_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            crash = root / "crash.log"
            crash.write_text("file=C:\\Users\\private\\song.mid\n", encoding="utf-8")
            target = root / "support.zip"
            with patch.object(support_bundle, "CRASH_LOG_PATH", crash):
                support_bundle.export_support_bundle(target)
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(
                    set(archive.namelist()),
                    {"support.json", "crash.log", "PRIVACY.txt"},
                )
                metadata = json.loads(archive.read("support.json"))
                self.assertEqual(metadata["schema"], 1)
                log = archive.read("crash.log").decode("utf-8")
                self.assertIn("<private-path>", log)
                self.assertNotIn("Users", log)

    def test_destination_must_be_zip(self) -> None:
        with self.assertRaises(ValueError):
            support_bundle.export_support_bundle("support.txt")

    def test_crash_log_rotation_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "crash.log"
            path.write_text("old", encoding="utf-8")
            with (
                patch.object(crash_logging, "CRASH_LOG_PATH", path),
                patch.object(crash_logging, "MAX_CRASH_LOG_BYTES", 1),
            ):
                crash_logging.append_crash_log("new", "detail")
            self.assertEqual(path.with_name("crash.log.1").read_text(), "old")
            self.assertIn("detail", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
