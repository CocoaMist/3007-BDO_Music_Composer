from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from bdo_experiments import AbExperimentRecord, read_experiment_records, write_experiment_records
from project_schema import CURRENT_PROJECT_SCHEMA, migrate_project


class ProjectSchemaExperimentTests(unittest.TestCase):
    def test_v1_project_migrates_without_losing_tracks(self) -> None:
        payload = migrate_project({"version": 1, "tracks": [{"track_id": 2}]})
        self.assertEqual(payload["schema_version"], CURRENT_PROJECT_SCHEMA)
        self.assertEqual(payload["tracks"][0]["track_id"], 2)
        self.assertIn("research", payload)

    def test_experiment_records_store_fingerprints_not_private_paths(self) -> None:
        record = AbExperimentRecord(
            "exp-1", "profile", "2026.07", 11, 0, "same note", "aligned",
            "verified", "abc123", "def456", "2026-07-15",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "experiments.json"
            write_experiment_records(path, [record])
            self.assertEqual(read_experiment_records(path), (record,))
        with self.assertRaises(ValueError):
            AbExperimentRecord(
                "bad", "profile", "2026.07", 11, 0, "", "", "inferred",
                r"C:\Users\private\score",
            )


if __name__ == "__main__":
    unittest.main()
