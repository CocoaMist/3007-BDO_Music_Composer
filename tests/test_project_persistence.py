import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bdo_midi import Note
from home_catalog import IncrementalHomeScan, scan_local_projects
from project_persistence import (
    AutosaveRequest,
    PROJECT_INDEX_NAME,
    ProjectTrackSnapshot,
    rename_project,
    write_autosave,
)


class ProjectPersistenceTests(unittest.TestCase):
    def test_autosave_writes_compact_project_and_safe_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_dir = Path(temp) / "demo"
            request = AutosaveRequest(
                project_dir=project_dir,
                metadata={"schema_version": 5, "output_name": "Demo"},
                tracks=(ProjectTrackSnapshot(
                    values={
                        "track_id": 1,
                        "gm_program": 0,
                        "is_percussion": False,
                        "display_name": "Lead",
                        "bdo_instrument_id": 0x0B,
                        "muted": False,
                        "solo": False,
                        "volume_scale": 1.0,
                        "duration_scale": 1.0,
                        "bdo_track_volume": 70,
                        "bdo_track_settings": (0,) * 8,
                        "bdo_source_group_index": None,
                        "bdo_source_note_records": (),
                        "articulation_type": None,
                        "marnian_synth_mode": "basic",
                        "notes_optimized": False,
                        "performance_controls": (),
                    },
                    notes=(Note(60, 90, 0.0, 250.0, 0),),
                ),),
                saved_at="2026-07-27 12:00:00",
                reason="test",
            )
            write_autosave(request)

            payload = json.loads((project_dir / "project.json").read_text("utf-8"))
            index = json.loads((project_dir / PROJECT_INDEX_NAME).read_text("utf-8"))
            self.assertEqual(payload["tracks"][0]["notes"], [[60, 90, 0.0, 250.0, 0]])
            self.assertEqual(index["output_name"], "Demo")
            self.assertEqual(index["project_id"], payload["project_id"])
            self.assertEqual(index["instrument_ids"], [0x0B])
            self.assertNotIn("tracks", index)

            second_id = json.loads(
                write_autosave(request).read_text("utf-8")
            )["project_id"]
            self.assertEqual(second_id, payload["project_id"])

    def test_project_rename_preserves_identity_and_rewrites_safe_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_dir = Path(temp) / "demo"
            project_dir.mkdir()
            project_path = project_dir / "project.json"
            project_path.write_text(
                json.dumps({
                    "project_id": "4c792f3e-83e2-4fc6-901c-4d8e6a69eb2e",
                    "output_name": "Before",
                    "tracks": [],
                }),
                encoding="utf-8",
            )

            project_id = rename_project(project_path, "After")

            payload = json.loads(project_path.read_text("utf-8"))
            index = json.loads((project_dir / PROJECT_INDEX_NAME).read_text("utf-8"))
            self.assertEqual(project_id, payload["project_id"])
            self.assertEqual(index["project_id"], project_id)
            self.assertEqual(payload["output_name"], "After")
            self.assertEqual(index["output_name"], "After")
            self.assertEqual(index["instrument_ids"], [])

    def test_scanner_applies_limit_before_reading_project_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old = root / "old"
            new = root / "new"
            old.mkdir()
            new.mkdir()
            (old / "project.json").write_bytes(b"x" * (1024 * 1024))
            (new / "project.json").write_text(
                '{"output_name":"Newest","tracks":[]}', encoding="utf-8"
            )
            os.utime(old / "project.json", (10, 10))
            os.utime(new / "project.json", (20, 20))

            entries = scan_local_projects(root, limit=1)

            self.assertEqual([entry.label for entry in entries], ["Newest"])

    def test_incremental_scan_is_bounded_and_reads_only_retained_projects(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            game = root / "music"
            projects = root / "projects"
            game.mkdir()
            projects.mkdir()
            for index in range(180):
                (game / f"score-{index}").write_bytes(b"score")
                project_dir = projects / f"project-{index}"
                project_dir.mkdir()
                (project_dir / "project.json").write_text(
                    json.dumps({"output_name": f"Project {index}"}),
                    encoding="utf-8",
                )
                os.utime(project_dir / "project.json", (index + 1, index + 1))

            with patch(
                "home_catalog.game_score_instrument_ids",
                return_value=(0x0B,),
            ) as instrument_scan:
                scan = IncrementalHomeScan(
                    game,
                    projects,
                    game_limit=10,
                    project_limit=12,
                )
                turns = 0
                while not scan.step(17):
                    turns += 1
                    self.assertLess(turns, 100)
                scores, entries = scan.results()

            self.assertGreater(turns, 1)
            self.assertEqual(len(scores), 10)
            self.assertEqual(instrument_scan.call_count, 10)
            self.assertTrue(all(entry.instrument_ids == (0x0B,) for entry in scores))
            self.assertEqual(len(entries), 12)
            self.assertEqual(entries[0].label, "Project 179")


if __name__ == "__main__":
    unittest.main()
