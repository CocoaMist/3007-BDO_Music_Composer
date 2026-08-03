from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import bdo_common.atomic_io as atomic_io
import bdo_music_composer.ui.main_window as gui


class ConfigAndMeterSafetyTests(unittest.TestCase):
    def test_corrupt_midi_meter_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            path = Path(folder_name) / "broken.mid"
            path.write_bytes(b"not a midi file")

            with self.assertRaisesRegex(ValueError, "已阻止导出"):
                gui.source_time_signature_denominator(path)

    def test_config_atomic_failure_preserves_previous_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            path = Path(folder_name) / "config.json"
            original = b'{"language":"zh_CN"}'
            path.write_bytes(original)

            with patch.object(gui, "CONFIG_PATH", path), patch.object(
                atomic_io.os,
                "replace",
                side_effect=OSError("injected replace failure"),
            ):
                with self.assertRaisesRegex(OSError, "injected replace failure"):
                    gui.save_config({"language": "en_US"})

            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.glob(".*.tmp")), [])

    def test_replacing_corrupt_config_keeps_recovery_copy(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            path = Path(folder_name) / "config.json"
            corrupt = b"{broken"
            path.write_bytes(corrupt)

            with patch.object(gui, "CONFIG_PATH", path):
                self.assertEqual(gui.load_config(), {})
                gui.save_config({"language": "en_US"})
                self.assertEqual(gui.load_config(), {"language": "en_US"})

            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"language": "en_US"},
            )
            backups = list(path.parent.glob("config.corrupt-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), corrupt)


if __name__ == "__main__":
    unittest.main()
