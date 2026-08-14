import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bdo_midi import Note
from bdo_music_composer.editor.arrangement_clip import plan_clip_edit
from bdo_music_composer.editor.editor_models import ArrangementClipState, TrackState
from bdo_music_composer.app.home_catalog import IncrementalHomeScan, scan_local_projects
from bdo_music_composer.project.project_persistence import (
    AUTOSAVE_LOG_MAX_BYTES,
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

    def test_diagnostic_log_is_bounded_and_never_invalidates_project_save(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_dir = Path(temp) / "demo"
            track = TrackState(1, [Note(60, 90, 0, 250, 0)], 0, False, "Lead", 0x0B)
            request = AutosaveRequest(
                project_dir,
                ProjectMetadataSnapshot.capture(
                    schema_version=13, saved_at="now",
                    reason="x" * 10_000, output_name="Bounded",
                ),
                freeze_project_tracks((track,)),
            )
            project_dir.mkdir()
            log_path = project_dir / "autosave.log"
            log_path.write_bytes(b"old-line\n" * (AUTOSAVE_LOG_MAX_BYTES // 9 + 2))

            write_autosave(request)

            self.assertLess(log_path.stat().st_size, AUTOSAVE_LOG_MAX_BYTES)
            self.assertEqual(
                json.loads((project_dir / "project.json").read_text("utf-8"))["output_name"],
                "Bounded",
            )
            log_path.unlink()
            log_path.mkdir()
            self.assertTrue(write_autosave(request).is_file())

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

    def test_track_snapshot_preserves_clip_bounds_and_arrangement_group(self) -> None:
        track = TrackState(4, [Note(64, 95, 100.0, 300.0, 0)], 12, False, "Clip", 0x0B)
        track.clip_start_ms = 150.0
        track.clip_end_ms = 350.0
        track.arrangement_group_id = "game-instrument:11"
        track.arrangement_clips = [ArrangementClipState(
            "clip-a", 500.0, 750.0, 100.0, 350.0, 400.0,
            "Verse", "#123456",
        )]
        payload = freeze_project_tracks((track,))[0].to_payload()
        self.assertEqual(payload["clip_start_ms"], 150.0)
        self.assertEqual(payload["clip_end_ms"], 350.0)
        self.assertEqual(payload["arrangement_group_id"], "game-instrument:11")
        self.assertEqual(payload["arrangement_clips"][0]["time_offset_ms"], 400.0)
        self.assertEqual(payload["arrangement_clips"][0]["clip_id"], "clip-a")
        self.assertEqual(payload["arrangement_clips"][0]["display_name"], "Verse")
        self.assertEqual(payload["arrangement_clips"][0]["color"], "#123456")

    def test_track_snapshot_preserves_empty_three_second_clip(self) -> None:
        from bdo_music_composer.editor.arrangement_clip import plan_clip_create

        track = TrackState(8, [], 0, False, "Empty Clip", 0x12)
        plan = plan_clip_create(
            track, start_ms=750.0, duration_ms=100.0
        )
        track.notes = list(plan.updates[0].notes)
        track.arrangement_clips = list(plan.updates[0].arrangement_clips)

        payload = freeze_project_tracks((track,))[0].to_payload()

        self.assertEqual(payload["notes"], [])
        self.assertEqual(
            (
                payload["arrangement_clips"][0]["start_ms"],
                payload["arrangement_clips"][0]["end_ms"],
            ),
            (750.0, 3_750.0),
        )

    def test_track_snapshot_preserves_resized_clip_payload_exactly(self) -> None:
        track = TrackState(
            9,
            [Note(60, 77, 100.0, 100.0, 5)],
            0,
            False,
            "Scaled",
            0x12,
            performance_controls=[{
                "time": 150.0,
                "kind": "control_change",
                "control": 64,
                "value": 127,
            }],
            bdo_source_note_records=(
                (60, 77, 100.0, 100.0, 5, 66),
            ),
            arrangement_clips=[ArrangementClipState(
                "scaled", 100.0, 300.0, 100.0, 300.0
            )],
        )
        update = plan_clip_edit(
            track,
            clip_id="scaled",
            mode="resize_end",
            new_start_ms=100.0,
            new_end_ms=500.0,
        ).updates[0]
        track.notes = list(update.notes)
        track.performance_controls = list(update.performance_controls)
        track.bdo_source_note_records = update.source_note_records
        track.arrangement_clips = list(update.arrangement_clips)

        payload = freeze_project_tracks((track,))[0].to_payload()

        self.assertEqual(payload["notes"], [[60, 77, 100.0, 100.0, 5]])
        self.assertEqual(payload["performance_controls"][0]["time"], 150.0)
        self.assertEqual(
            payload["bdo_source_note_records"],
            [[60, 77, 100.0, 100.0, 5, 66]],
        )
        self.assertEqual(
            (
                payload["arrangement_clips"][0]["start_ms"],
                payload["arrangement_clips"][0]["end_ms"],
            ),
            (100.0, 500.0),
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
