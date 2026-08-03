from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bdo_common.atomic_io as atomic_io
from bdo_music_composer.export.bdo_score import read_bdo_score
from scripts import wpf_sidecar


class WpfSidecarTests(unittest.TestCase):
    def project(self) -> dict:
        return {
            "schema_version": 2, "owner_id": 123, "char_name": "Owner", "bpm": 120, "time_sig": 4,
            "conversion_settings": {"transpose": 0, "velocity_mode": "preserve", "reverb": 0, "delay": 0},
            "tracks": [{"track_id": 1, "gm_program": 0, "is_percussion": False, "display_name": "lead", "bdo_instrument_id": 0x0B, "notes": [[60, 90, 0, 400, 3]]}],
        }

    def test_handshake_advertises_capabilities(self) -> None:
        result = wpf_sidecar.dispatch("handshake", {})
        self.assertEqual(result["protocol"], "ndjson")
        self.assertIn("export_bdo", result["capabilities"])
        self.assertIn("import_bdo", result["capabilities"])

    def test_export_uses_snapshot_note_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out_path = Path(directory) / "score"
            result = wpf_sidecar.dispatch("export_bdo", {"project": self.project(), "out_path": str(out_path)})
            self.assertTrue(result["exported"])
            self.assertTrue(out_path.is_file())
            self.assertGreater(out_path.stat().st_size, 4)

    def test_mute_solo_never_remove_formal_export_tracks(self) -> None:
        project = self.project()
        project["tracks"][0].update({"muted": True, "solo": False})
        issues = wpf_sidecar.dispatch(
            "validate_project", {"project": project}
        )["issues"]
        self.assertFalse(any(item["code"] == "track.excluded" for item in issues))
        with tempfile.TemporaryDirectory() as directory:
            out_path = Path(directory) / "muted-score"
            result = wpf_sidecar.dispatch(
                "export_bdo",
                {"project": project, "out_path": str(out_path)},
            )
            self.assertTrue(result["exported"])
            self.assertEqual(read_bdo_score(out_path).total_notes, 1)

    def test_unmaterialized_velocity_policy_is_blocked(self) -> None:
        project = self.project()
        project["conversion_settings"]["velocity_mode"] = "layered"
        result = wpf_sidecar.dispatch(
            "export_bdo", {"project": project, "out_path": "ignored"}
        )
        self.assertFalse(result["exported"])
        self.assertTrue(any(
            item["code"] == "game_model.velocity_unmaterialized"
            for item in result["issues"]
        ))

    def test_marnian_mode_offset_is_the_exported_instrument_id(self) -> None:
        project = self.project()
        project["tracks"][0].update({
            "bdo_instrument_id": 20,
            "marnian_synth_mode": "stereo",
        })
        with tempfile.TemporaryDirectory() as directory:
            out_path = Path(directory) / "marnian-score"
            result = wpf_sidecar.dispatch(
                "export_bdo",
                {"project": project, "out_path": str(out_path)},
            )
            self.assertTrue(result["exported"])
            active = next(
                track
                for track in read_bdo_score(out_path).tracks
                if track.notes
            )
            self.assertEqual(active.instrument_id, 21)

    def test_export_and_validation_share_track_pitch_plan(self) -> None:
        project = self.project()
        project["pitch_transform"] = {
            "global_semitones": 0,
            "track_overrides": [
                {
                    "track_id": 1,
                    "semitones": 12,
                    "mode": "octave",
                    "provenance": "user",
                }
            ],
        }
        issues = wpf_sidecar.dispatch(
            "validate_project", {"project": project}
        )["issues"]
        transpose = next(
            item for item in issues if item["code"] == "export.transpose"
        )
        self.assertEqual(transpose["track_id"], 1)

        with tempfile.TemporaryDirectory() as directory:
            out_path = Path(directory) / "score"
            result = wpf_sidecar.dispatch(
                "export_bdo",
                {"project": project, "out_path": str(out_path)},
            )
            self.assertTrue(result["exported"])
            pitches = [
                note.pitch
                for track in read_bdo_score(out_path).tracks
                for note in track.notes
            ]
            self.assertEqual(pitches, [72])

    def test_drum_target_with_melodic_source_flag_stays_at_canonical_pitch(self) -> None:
        project = self.project()
        project["conversion_settings"]["transpose"] = -8
        project["pitch_transform"] = {
            "global_semitones": -8,
            "track_overrides": [],
        }
        project["tracks"][0].update({
            "is_percussion": False,
            "bdo_instrument_id": 0x0D,
            "notes": [[48, 90, 0, 250, 99]],
        })

        issues = wpf_sidecar.dispatch(
            "validate_project", {"project": project}
        )["issues"]
        self.assertFalse(any(
            issue["code"] == "export.transpose" for issue in issues
        ))
        self.assertFalse(any(
            issue["severity"] == "error" for issue in issues
        ))

        with tempfile.TemporaryDirectory() as directory:
            out_path = Path(directory) / "drums.bdo"
            result = wpf_sidecar.dispatch(
                "export_bdo",
                {"project": project, "out_path": str(out_path)},
            )
            self.assertTrue(result["exported"])
            notes = [
                note
                for track in read_bdo_score(out_path).tracks
                for note in track.notes
            ]
        self.assertEqual(
            [(note.pitch, note.ntype) for note in notes],
            [(48, 99)],
        )

    def test_invalid_meter_blocks_export(self) -> None:
        project = self.project(); project["time_sig"] = 3
        result = wpf_sidecar.dispatch("export_bdo", {"project": project, "out_path": "ignored"})
        self.assertFalse(result["exported"])
        self.assertTrue(any(issue["code"] == "meter.unsupported" for issue in result["issues"]))

    def test_import_bdo_rebuilds_editable_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out_path = Path(directory) / "score"
            exported = wpf_sidecar.dispatch("export_bdo", {"project": self.project(), "out_path": str(out_path)})
            self.assertTrue(exported["exported"])
            imported = wpf_sidecar.dispatch("import_bdo", {"score_path": str(out_path)})["project"]
            self.assertEqual(imported["owner_id"], 123)
            self.assertEqual(imported["tracks"][0]["notes"][0], [60, 90, 0.0, 400.0, 3])
            self.assertEqual(imported["path_policy"], "project-relative-v1")
            self.assertEqual(imported["source_bdo_path"], "")
            self.assertNotIn(str(Path(directory).resolve()), str(imported))

    def test_export_failure_preserves_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out_path = Path(directory) / "score"
            out_path.write_bytes(b"known-good")
            with patch.object(atomic_io.os, "replace", side_effect=OSError("busy")):
                with self.assertRaises(OSError):
                    wpf_sidecar.dispatch(
                        "export_bdo",
                        {"project": self.project(), "out_path": str(out_path)},
                    )
            self.assertEqual(out_path.read_bytes(), b"known-good")
            self.assertEqual(
                list(out_path.parent.glob(f".{out_path.name}.*.tmp")),
                [],
            )

    def test_optimizer_preview_and_apply_use_snapshot_fingerprint(self) -> None:
        project = self.project()
        project["tracks"][0]["notes"].append([62, 100, 500, 300, 0])
        preview = wpf_sidecar.dispatch("optimise_preview", {
            "project": project, "algorithm_id": "bdo-safe", "intensity": "conservative",
            "scope": "global", "target_track_ids": [1],
        })
        self.assertIn("preview_project", preview)
        applied = wpf_sidecar.dispatch("optimise_apply", {"project": project, "preview": preview})
        self.assertTrue(applied["applied"])

        changed = self.project()
        changed["tracks"][0]["notes"][0][1] = 80
        with self.assertRaisesRegex(ValueError, "重新运行"):
            wpf_sidecar.dispatch("optimise_apply", {"project": changed, "preview": preview})


if __name__ == "__main__":
    unittest.main()
