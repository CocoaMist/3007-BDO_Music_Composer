import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bdo_midi import Note
from bdo_music_composer.editor.editor_models import TrackState
from bdo_music_composer.app.home_catalog import IncrementalHomeScan, scan_local_projects
from bdo_music_composer.project.project_persistence import (
    AutosaveRequest,
    PROJECT_INDEX_NAME,
    ProjectMetadataSnapshot,
    freeze_project_tracks,
    rename_project,
    write_autosave,
)


class ProjectPersistenceTests(unittest.TestCase):
    def test_autosave_writes_compact_project_and_safe_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_dir = Path(temp) / "demo"
            track = TrackState(
                track_id=1,
                notes=[Note(60, 90, 0.0, 250.0, 0)],
                gm_program=0,
                is_percussion=False,
                display_name="Lead",
                bdo_instrument_id=0x0B,
            )
            request = AutosaveRequest(
                project_dir=project_dir,
                metadata=ProjectMetadataSnapshot.capture(
                    schema_version=5,
                    output_name="Demo",
                    saved_at="2026-07-27 12:00:00",
                    reason="test",
                ),
                tracks=freeze_project_tracks((track,)),
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

    def test_metadata_snapshot_recursively_detaches_mutable_ui_values(
        self,
    ) -> None:
        lyrics = [{"time": 1.0, "text": "before"}]
        research = {
            "profile_id": "profile",
            "ab_experiments": [{"id": "before"}],
        }
        snapshot = ProjectMetadataSnapshot.capture(
            schema_version=11,
            saved_at="2026-07-30 12:00:00",
            reason="test",
            lyric_events=lyrics,
            research=research,
        )

        lyrics[0]["text"] = "after"
        research["ab_experiments"][0]["id"] = "after"
        payload = snapshot.to_payload()

        self.assertEqual(payload["lyric_events"][0]["text"], "before")
        self.assertEqual(
            payload["research"]["ab_experiments"][0]["id"],
            "before",
        )
        self.assertEqual(payload["original_midi_path"], "")
        self.assertEqual(payload["reference_audio_path"], "")

    def test_metadata_snapshot_rejects_nonportable_source_reference(self) -> None:
        for reference in ("../source.mid", str(Path.cwd().resolve())):
            with self.subTest(reference=reference):
                with self.assertRaisesRegex(ValueError, "project-relative"):
                    ProjectMetadataSnapshot.capture(
                        schema_version=11,
                        source_reference=reference,
                    )

    def test_track_snapshot_recursively_detaches_mutable_editor_values(
        self,
    ) -> None:
        track = TrackState(
            track_id=4,
            notes=[Note(64, 95, 100.0, 300.0, 7)],
            gm_program=12,
            is_percussion=False,
            display_name="Before",
            bdo_instrument_id=0x0B,
            performance_controls=[{
                "kind": "cc",
                "value": 64,
                "metadata": {"label": "before"},
            }],
        )
        snapshot = freeze_project_tracks((track,))[0]

        track.display_name = "After"
        track.notes.append(Note(67, 80, 500.0, 100.0, 0))
        track.performance_controls[0]["value"] = 0
        track.performance_controls[0]["metadata"]["label"] = "after"
        payload = snapshot.to_payload()

        self.assertEqual(payload["display_name"], "Before")
        self.assertEqual(payload["notes"], [[64, 95, 100.0, 300.0, 7]])
        self.assertEqual(payload["performance_controls"][0]["value"], 64)
        self.assertEqual(
            payload["performance_controls"][0]["metadata"]["label"],
            "before",
        )

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
                "bdo_music_composer.app.home_catalog.game_score_instrument_ids",
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
