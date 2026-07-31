from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import atomic_io
from bdo_experiments import AbExperimentRecord, read_experiment_records, write_experiment_records
from bdo_music_composer.project.project_schema import (
    CURRENT_PROJECT_SCHEMA,
    DEFAULT_REFERENCE_LAYER_SETTINGS,
    migrate_project,
    normalize_reference_layer_settings,
    project_relative_file_reference,
    resolve_project_file_reference,
)


class ProjectSchemaExperimentTests(unittest.TestCase):
    def test_v1_project_migrates_without_losing_tracks(self) -> None:
        payload = migrate_project({"version": 1, "tracks": [{"track_id": 2}]})
        self.assertEqual(payload["schema_version"], CURRENT_PROJECT_SCHEMA)
        self.assertEqual(payload["tracks"][0]["bdo_track_volume"], 70)
        self.assertEqual(payload["tracks"][0]["bdo_track_settings"], [0] * 8)
        self.assertEqual(payload["tracks"][0]["track_id"], 2)
        self.assertIn("research", payload)
        self.assertEqual(payload["reference_audio_offset_ms"], 0.0)
        self.assertEqual(payload["beat_origin_ms"], 0.0)
        self.assertEqual(
            payload["transcription_review"],
            {
                "analysis_mode": "standard",
                "cleanup_profile": "preserve",
                "version": 4,
            },
        )
        self.assertEqual(payload["transcription_assist_review"], {})
        self.assertEqual(
            payload["reference_layers"]["background_opacity_percent"],
            100,
        )

    def test_v3_project_gains_transcription_defaults_without_overwriting_data(self) -> None:
        review = {
            "version": 1,
            "cache_key": "keep",
            "rejected_candidate_ids": ["candidate-a"],
        }
        payload = migrate_project(
            {
                "schema_version": 3,
                "reference_audio_offset_ms": -250.5,
                "transcription_review": review,
                "tracks": [],
            }
        )
        self.assertEqual(payload["schema_version"], CURRENT_PROJECT_SCHEMA)
        self.assertEqual(payload["reference_audio_offset_ms"], -250.5)
        self.assertEqual(payload["beat_origin_ms"], 0.0)
        self.assertEqual(
            payload["transcription_review"],
            {
                **review,
                "version": 4,
                "analysis_mode": "standard",
                "cleanup_profile": "preserve",
            },
        )
        self.assertEqual(payload["transcription_assist_review"], {})

    def test_current_project_migration_is_idempotent_and_isolated(self) -> None:
        source = {"schema_version": CURRENT_PROJECT_SCHEMA, "tracks": []}
        first = migrate_project(source)
        second = migrate_project(first)
        self.assertEqual(first, second)
        self.assertEqual(
            first["transcription_review"],
            {"version": 4, "cleanup_profile": "preserve"},
        )
        first["transcription_review"]["changed"] = True
        self.assertEqual(
            source,
            {"schema_version": CURRENT_PROJECT_SCHEMA, "tracks": []},
        )

    def test_v7_cleanup_choice_migrates_to_preserve_without_losing_review(self) -> None:
        source = {
            "schema_version": 7,
            "tracks": [],
            "transcription_review": {
                "version": 3,
                "analysis_mode": "mixed_enhanced",
                "cleanup_profile": "clean",
                "rejected_candidate_ids": ["reviewed-note"],
            },
        }

        payload = migrate_project(source)

        self.assertEqual(payload["schema_version"], CURRENT_PROJECT_SCHEMA)
        self.assertEqual(
            payload["transcription_review"],
            {
                "version": 4,
                "analysis_mode": "mixed_enhanced",
                "cleanup_profile": "preserve",
                "rejected_candidate_ids": ["reviewed-note"],
            },
        )

    def test_v8_review_v4_preserves_explicit_cleanup_choice(self) -> None:
        for cleanup_profile in ("balanced", "clean"):
            with self.subTest(cleanup_profile=cleanup_profile):
                source = {
                    "schema_version": 8,
                    "tracks": [],
                    "transcription_review": {
                        "version": 4,
                        "cleanup_profile": cleanup_profile,
                        "selected_candidate_ids": ["candidate"],
                    },
                }

                payload = migrate_project(source)

                self.assertEqual(
                    payload["transcription_review"],
                    source["transcription_review"],
                )

    def test_v4_project_gains_empty_assist_review(self) -> None:
        review = {"version": 1, "selected_candidate_ids": ["candidate"]}
        payload = migrate_project(
            {
                "schema_version": 4,
                "tracks": [],
                "transcription_review": review,
            }
        )
        self.assertEqual(payload["schema_version"], CURRENT_PROJECT_SCHEMA)
        self.assertEqual(
            payload["transcription_review"],
            {
                **review,
                "version": 4,
                "analysis_mode": "standard",
                "cleanup_profile": "preserve",
            },
        )
        self.assertEqual(payload["transcription_assist_review"], {})

    def test_v6_project_defaults_to_preserve_cleanup(self) -> None:
        payload = migrate_project(
            {
                "schema_version": 6,
                "tracks": [],
                "transcription_review": {
                    "version": 3,
                    "cleanup_profile": "clean",
                },
            }
        )

        self.assertEqual(payload["schema_version"], CURRENT_PROJECT_SCHEMA)
        self.assertEqual(
            payload["transcription_review"]["cleanup_profile"],
            "preserve",
        )
        self.assertEqual(payload["transcription_review"]["version"], 4)

    def test_v8_reference_layers_preserve_pre_control_visual_strength(self) -> None:
        payload = migrate_project({"schema_version": 8, "tracks": []})

        self.assertEqual(payload["schema_version"], CURRENT_PROJECT_SCHEMA)
        self.assertEqual(payload["reference_layers"]["ghost_opacity_percent"], 100)
        self.assertEqual(
            payload["reference_layers"]["background_opacity_percent"],
            100,
        )

    def test_v9_pitch_transform_migration_uses_saved_global_transpose(self) -> None:
        payload = migrate_project(
            {
                "schema_version": 9,
                "conversion_settings": {"transpose": -8},
                "tracks": [{"track_id": 7}],
            }
        )

        self.assertEqual(payload["schema_version"], CURRENT_PROJECT_SCHEMA)
        self.assertEqual(
            payload["pitch_transform"],
            {"global_semitones": -8, "track_overrides": []},
        )
        self.assertEqual(payload["conversion_settings"]["transpose"], -8)
        self.assertEqual(
            payload["conversion_settings"]["velocity_mode"],
            "preserve",
        )

    def test_new_reference_layers_are_bounded_and_quiet(self) -> None:
        self.assertEqual(
            DEFAULT_REFERENCE_LAYER_SETTINGS["ghost_opacity_percent"],
            24,
        )
        self.assertEqual(
            DEFAULT_REFERENCE_LAYER_SETTINGS["background_opacity_percent"],
            45,
        )
        self.assertEqual(
            normalize_reference_layer_settings(None),
            DEFAULT_REFERENCE_LAYER_SETTINGS,
        )
        normalized = normalize_reference_layer_settings(
            {
                "ghost_visible": False,
                "ghost_opacity_percent": 120,
                "background_opacity_percent": -4,
                "frame_visible": True,
            }
        )
        self.assertFalse(normalized["ghost_visible"])
        self.assertEqual(normalized["ghost_opacity_percent"], 100)
        self.assertEqual(normalized["background_opacity_percent"], 0)
        self.assertTrue(normalized["frame_visible"])

    def test_old_default_ghost_opacity_migrates_without_overwriting_custom_value(self) -> None:
        migrated_default = normalize_reference_layer_settings(
            {"version": 1, "ghost_opacity_percent": 70}
        )
        preserved_custom = normalize_reference_layer_settings(
            {"version": 1, "ghost_opacity_percent": 58}
        )

        self.assertEqual(migrated_default["version"], 3)
        self.assertEqual(migrated_default["ghost_opacity_percent"], 24)
        self.assertEqual(preserved_custom["ghost_opacity_percent"], 58)

    def test_v2_quiet_defaults_migrate_to_lower_density_without_overwriting_custom_values(self) -> None:
        migrated_defaults = normalize_reference_layer_settings(
            {
                "version": 2,
                "ghost_opacity_percent": 40,
                "background_opacity_percent": 60,
            }
        )
        preserved_custom = normalize_reference_layer_settings(
            {
                "version": 2,
                "ghost_opacity_percent": 31,
                "background_opacity_percent": 52,
            }
        )

        self.assertEqual(migrated_defaults["version"], 3)
        self.assertEqual(migrated_defaults["ghost_opacity_percent"], 24)
        self.assertEqual(migrated_defaults["background_opacity_percent"], 45)
        self.assertEqual(preserved_custom["ghost_opacity_percent"], 31)
        self.assertEqual(preserved_custom["background_opacity_percent"], 52)

    def test_project_file_reference_round_trips_only_inside_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_dir = root / "project"
            project_dir.mkdir()
            source = project_dir / "assets" / "source.mid"
            source.parent.mkdir()
            source.write_bytes(b"MThd")
            outside = root / "outside.mid"
            outside.write_bytes(b"private")

            reference = project_relative_file_reference(project_dir, source)

            self.assertEqual(reference, "assets/source.mid")
            self.assertEqual(
                resolve_project_file_reference(project_dir, reference),
                source.resolve(),
            )
            self.assertEqual(
                project_relative_file_reference(project_dir, outside),
                "",
            )

    def test_project_file_reference_rejects_traversal_and_current_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_dir = root / "project"
            project_dir.mkdir()
            outside = root / "outside.mid"
            outside.write_bytes(b"private")

            self.assertIsNone(
                resolve_project_file_reference(project_dir, "../outside.mid")
            )
            self.assertIsNone(
                resolve_project_file_reference(project_dir, outside)
            )
            self.assertEqual(
                resolve_project_file_reference(
                    project_dir,
                    outside,
                    allow_legacy_absolute=True,
                ),
                outside.resolve(),
            )

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

    def test_experiment_write_failure_preserves_existing_destination(self) -> None:
        record = AbExperimentRecord(
            "exp-1", "profile", "2026.07", 11, 0, "same note", "aligned",
            "verified", "abc123", "def456", "2026-07-15",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "experiments.json"
            path.write_text("known-good", encoding="utf-8")
            with patch.object(atomic_io.os, "replace", side_effect=OSError("busy")):
                with self.assertRaises(OSError):
                    write_experiment_records(path, [record])
            self.assertEqual(path.read_text(encoding="utf-8"), "known-good")
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
