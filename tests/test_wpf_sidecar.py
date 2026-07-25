from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import wpf_sidecar


class WpfSidecarTests(unittest.TestCase):
    def project(self) -> dict:
        return {
            "schema_version": 2, "owner_id": 123, "char_name": "Owner", "bpm": 120, "time_sig": 4,
            "conversion_settings": {"transpose": 0, "velocity_mode": "preserve", "reverb": 0, "delay": 0},
            "tracks": [{"track_id": 1, "gm_program": 0, "is_percussion": False, "display_name": "lead", "bdo_instrument_id": 0x0B, "notes": [[60, 90, 0, 400, 7]]}],
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
            self.assertEqual(imported["tracks"][0]["notes"][0], [60, 90, 0.0, 400.0, 7])
            self.assertEqual(imported["source_bdo_path"], str(out_path.resolve()))

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
