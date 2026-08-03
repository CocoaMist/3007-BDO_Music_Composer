from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import bdo_music_composer.core.project_paths as project_paths


class ProjectPathsTests(unittest.TestCase):
    def test_user_data_dir_uses_override_then_local_app_data(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            override = root / "portable-user-data"
            with patch.dict(
                os.environ,
                {
                    "BDO_USER_DATA_DIR": str(override),
                    "LOCALAPPDATA": str(root / "local"),
                },
            ):
                self.assertEqual(project_paths._user_data_dir(), override)
            with patch.dict(
                os.environ,
                {"LOCALAPPDATA": str(root / "local")},
            ):
                os.environ.pop("BDO_USER_DATA_DIR", None)
                self.assertEqual(
                    project_paths._user_data_dir(),
                    root / "local" / "BDO Music Composer",
                )

    def test_transcription_cache_uses_explicit_override_first(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            expected = Path(folder_name) / "custom-cache"
            with patch.dict(
                os.environ,
                {
                    "BDO_TRANSCRIPTION_CACHE": str(expected),
                    "LOCALAPPDATA": str(Path(folder_name) / "local"),
                },
            ):
                self.assertEqual(
                    project_paths._transcription_cache_dir(),
                    expected,
                )

    def test_transcription_cache_defaults_under_local_app_data(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            local_app_data = Path(folder_name) / "local"
            with patch.dict(
                os.environ,
                {"LOCALAPPDATA": str(local_app_data)},
            ):
                os.environ.pop("BDO_TRANSCRIPTION_CACHE", None)
                os.environ.pop("BDO_USER_DATA_DIR", None)
                self.assertEqual(
                    project_paths._transcription_cache_dir(),
                    local_app_data
                    / "BDO Music Composer"
                    / "transcription_cache",
                )


if __name__ == "__main__":
    unittest.main()
