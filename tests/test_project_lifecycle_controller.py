from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import uuid

from bdo_music_composer.project.project_lifecycle_controller import (
    ProjectOpenError,
    ProjectOpenErrorCode,
    ProjectOpenRequest,
    ProjectSourceFormat,
)


class ProjectOpenRequestTests(unittest.TestCase):
    def test_blank_project_needs_no_recovery_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_path = Path(temp) / "demo" / "project.json"
            request = ProjectOpenRequest.from_payload(
                project_path,
                {
                    "source_format": "project",
                    "path_policy": "project-relative-v1",
                    "output_name": "Blank score",
                },
            )

        self.assertIs(request.source_format, ProjectSourceFormat.PROJECT)
        self.assertIsNone(request.source_path)
        self.assertIsNone(request.source_copy_path)
        self.assertEqual(request.output_name, "Blank score")
        self.assertEqual(str(uuid.UUID(request.project_id)), request.project_id)

    def test_recovery_copy_wins_over_original_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_dir = Path(temp) / "demo"
            project_dir.mkdir()
            recovery = project_dir / "source.mid"
            original = project_dir / "original.mid"
            recovery.write_bytes(b"recovery")
            original.write_bytes(b"original")

            request = ProjectOpenRequest.from_payload(
                project_dir / "project.json",
                {
                    "source_format": "midi",
                    "path_policy": "project-relative-v1",
                    "source_midi_path": recovery.name,
                    "original_midi_path": original.name,
                },
            )

        self.assertIs(request.source_format, ProjectSourceFormat.MIDI)
        self.assertEqual(request.source_path, recovery.resolve())
        self.assertEqual(request.source_copy_path, recovery.resolve())
        self.assertFalse(request.allow_legacy_absolute_paths)

    def test_missing_recovery_copy_falls_back_without_marking_a_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_dir = Path(temp) / "demo"
            project_dir.mkdir()
            original = project_dir / "original.bdo"
            original.write_bytes(b"score")

            request = ProjectOpenRequest.from_payload(
                project_dir / "project.json",
                {
                    "source_format": "bdo",
                    "path_policy": "project-relative-v1",
                    "source_midi_path": "missing.bdo",
                    "original_midi_path": original.name,
                },
            )

        self.assertIs(request.source_format, ProjectSourceFormat.BDO)
        self.assertEqual(request.source_path, original.resolve())
        self.assertIsNone(request.source_copy_path)

    def test_complete_snapshot_remains_openable_without_provenance_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_dir = Path(temp) / "demo"
            project_dir.mkdir()
            request = ProjectOpenRequest.from_payload(
                project_dir / "project.json",
                {
                    "source_format": "midi",
                    "path_policy": "project-relative-v1",
                    "source_midi_path": "deleted-source.mid",
                    "tracks": [],
                },
            )

        self.assertIs(request.source_format, ProjectSourceFormat.MIDI)
        self.assertIsNone(request.source_path)
        self.assertIsNone(request.source_copy_path)

    def test_current_policy_rejects_absolute_and_traversal_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project_dir = root / "demo"
            project_dir.mkdir()
            external = root / "external.mid"
            external.write_bytes(b"midi")

            for reference in (str(external.resolve()), "../external.mid"):
                with self.subTest(reference=reference):
                    with self.assertRaises(ProjectOpenError) as caught:
                        ProjectOpenRequest.from_payload(
                            project_dir / "project.json",
                            {
                                "source_format": "midi",
                                "path_policy": "project-relative-v1",
                                "source_midi_path": reference,
                            },
                        )
                    self.assertIs(
                        caught.exception.code,
                        ProjectOpenErrorCode.MISSING_SOURCE,
                    )

    def test_legacy_project_may_use_existing_absolute_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project_dir = root / "demo"
            project_dir.mkdir()
            external = root / "legacy.mid"
            external.write_bytes(b"midi")

            request = ProjectOpenRequest.from_payload(
                project_dir / "project.json",
                {
                    "source_format": "midi",
                    "source_midi_path": str(external.resolve()),
                },
            )

        self.assertTrue(request.allow_legacy_absolute_paths)
        self.assertEqual(request.source_path, external.resolve())

    def test_unknown_source_format_keeps_legacy_midi_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_dir = Path(temp) / "demo"
            project_dir.mkdir()
            source = project_dir / "source.mid"
            source.write_bytes(b"midi")

            request = ProjectOpenRequest.from_payload(
                project_dir / "project.json",
                {
                    "source_format": "future-format",
                    "path_policy": "project-relative-v1",
                    "source_midi_path": source.name,
                },
            )

        self.assertIs(request.source_format, ProjectSourceFormat.MIDI)


if __name__ == "__main__":
    unittest.main()
