from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import bdo_common.atomic_io as atomic_io
from bdo_music_composer.app.application_config import (
    load_config,
    safe_filename,
    save_config,
)


class ApplicationConfigTests(unittest.TestCase):
    def test_missing_or_unusable_config_loads_as_empty_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            missing = root / "missing.json"
            self.assertEqual(load_config(missing), {})

            malformed = root / "malformed.json"
            malformed.write_bytes(b"{broken")
            self.assertEqual(load_config(malformed), {})
            self.assertEqual(malformed.read_bytes(), b"{broken")

            non_object = root / "list.json"
            non_object.write_text("[]", encoding="utf-8")
            self.assertEqual(load_config(non_object), {})

            invalid_utf8 = root / "invalid-utf8.json"
            invalid_utf8.write_bytes(b"\xff\xfe")
            self.assertEqual(load_config(invalid_utf8), {})

    def test_save_creates_parent_and_preserves_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            path = Path(folder_name) / "missing" / "nested" / "config.json"
            payload = {
                "language": "ja_JP",
                "future_feature": {
                    "enabled": True,
                    "labels": ["保留", "未知字段"],
                },
            }

            save_config(path, payload)

            self.assertTrue(path.is_file())
            self.assertEqual(load_config(path), payload)
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                payload,
            )

            restored = load_config(path)
            restored["language"] = "ko_KR"
            save_config(path, restored)
            self.assertEqual(
                load_config(path)["future_feature"],
                payload["future_feature"],
            )

    def test_save_rejects_non_dictionary_root_without_touching_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            path = Path(folder_name) / "config.json"
            original = b'{"language":"en_US"}'
            path.write_bytes(original)

            with self.assertRaisesRegex(TypeError, "must be a mapping"):
                save_config(path, ["not", "an", "object"])  # type: ignore[arg-type]

            self.assertEqual(path.read_bytes(), original)

    def test_corrupt_config_is_backed_up_before_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            path = root / "config.json"
            corrupt = b"{broken"
            path.write_bytes(corrupt)
            first_backup = root / "config.corrupt-20260730-123456.json"
            first_backup.write_bytes(b"older recovery")

            with patch(
                "bdo_music_composer.app.application_config.time.strftime",
                return_value="20260730-123456",
            ):
                save_config(path, {"language": "en_US"})

            backup = root / "config.corrupt-20260730-123456-2.json"
            self.assertEqual(backup.read_bytes(), corrupt)
            self.assertEqual(load_config(path), {"language": "en_US"})
            self.assertEqual(first_backup.read_bytes(), b"older recovery")

    def test_atomic_replace_failure_keeps_last_known_good_config(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            path = Path(folder_name) / "config.json"
            original = b'{"language":"en_US","future":true}'
            path.write_bytes(original)

            with patch.object(
                atomic_io.os,
                "replace",
                side_effect=OSError("injected replace failure"),
            ):
                with self.assertRaisesRegex(OSError, "injected replace failure"):
                    save_config(path, {"language": "ja_JP"})

            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.glob(".*.tmp")), [])

    def test_safe_filename_matches_legacy_windows_rules(self) -> None:
        self.assertEqual(
            safe_filename('  My<>:"/\\|?*\n Score...  '),
            "My__________ Score",
        )
        self.assertEqual(safe_filename("中文曲谱"), "中文曲谱")
        self.assertEqual(safe_filename(" ._* ", "未命名项目"), "未命名项目")
        self.assertEqual(safe_filename("x" * 100), "x" * 80)


if __name__ == "__main__":
    unittest.main()
