from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import project_paths


class ProjectPathsTests(unittest.TestCase):
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
                self.assertEqual(
                    project_paths._transcription_cache_dir(),
                    local_app_data
                    / "BDO Music Composer"
                    / "transcription_cache",
                )


if __name__ == "__main__":
    unittest.main()
