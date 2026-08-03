from __future__ import annotations

from copy import deepcopy
import unittest
from unittest.mock import patch

from bdo_export import channel_groups_to_bdo
from bdo_midi import Note
from bdo_music_composer.core.conversion_settings import ConversionSettings
from bdo_music_composer.project.project_schema import (
    CURRENT_PROJECT_SCHEMA,
    migrate_project,
)


_MODE_PARAMETERS: dict[str, dict[str, object]] = {
    "preserve": {},
    "off": {},
    "layered": {},
    "rescale": {"vel_range": [25, 115]},
    "floor": {"vel_floor": 44},
    "stepped": {"vel_floor": 36, "vel_step": [36, 13]},
}

_GOLDEN_VELOCITIES_AT_075 = {
    "preserve": [15, 45, 75, 95],
    "off": [15, 45, 75, 95],
    "layered": [60, 68, 75, 91],
    "rescale": [19, 44, 69, 86],
    "floor": [33, 95, 95, 95],
    "stepped": [27, 37, 95, 95],
}


def _project_payload(
    mode: str,
    scale: float,
    note_types: tuple[int, ...],
) -> dict[str, object]:
    velocities = (20, 60, 100, 127)
    notes = [
        [
            60 + index,
            velocity,
            float(index * 100),
            80.0,
            note_types[index % len(note_types)],
            f"future-column-{index}",
        ]
        for index, velocity in enumerate(velocities)
    ]
    return {
        "schema_version": 10,
        "source_format": "midi",
        "conversion_settings": {
            "transpose": 0,
            "velocity_mode": mode,
            **_MODE_PARAMETERS[mode],
        },
        "tracks": [
            {
                "track_id": 7,
                "volume_scale": scale,
                "notes": notes,
            }
        ],
    }


def _notes_from_project(payload: dict[str, object]) -> list[Note]:
    tracks = payload["tracks"]
    assert isinstance(tracks, list)
    raw_notes = tracks[0]["notes"]
    return [Note(*raw_note[:5]) for raw_note in raw_notes]


def _legacy_export(
    notes: list[Note],
    *,
    mode: str,
    scale: float,
) -> bytes:
    parameters = _MODE_PARAMETERS[mode]
    data, _summary = channel_groups_to_bdo(
        120,
        4,
        [(notes, 0, False)],
        char_name="VelocityMigration",
        owner_id=123,
        instrument_map={0: 0x0B},
        vel_range=(
            tuple(parameters["vel_range"])
            if mode == "rescale"
            else None
        ),
        vel_floor=(
            parameters.get("vel_floor")
            if mode in {"floor", "stepped"}
            else None
        ),
        vel_step=(
            tuple(parameters["vel_step"])
            if mode == "stepped"
            else None
        ),
        vel_layered=mode == "layered",
        vel_scales={0: scale},
        preserve_note_types=True,
    )
    return data


def _game_native_export(notes: list[Note]) -> bytes:
    data, _summary = channel_groups_to_bdo(
        120,
        4,
        [(notes, 0, False)],
        char_name="VelocityMigration",
        owner_id=123,
        instrument_map={0: 0x0B},
        preserve_note_types=True,
    )
    return data


class ProjectSchemaVelocityMigrationTests(unittest.TestCase):
    def test_current_schema_does_not_rerun_historical_velocity_bake(self) -> None:
        source = _project_payload("preserve", 1.0, (0,))
        source["schema_version"] = CURRENT_PROJECT_SCHEMA

        with patch(
            "bdo_music_composer.project.project_schema._bake_game_velocity_policy"
        ) as bake:
            migrated = migrate_project(source)

        bake.assert_not_called()
        self.assertEqual(
            [raw_note[1] for raw_note in migrated["tracks"][0]["notes"]],
            [20, 60, 100, 127],
        )

    def test_current_schema_normalizes_off_to_canonical_preserve(self) -> None:
        source = _project_payload("off", 1.0, (0,))
        source["schema_version"] = CURRENT_PROJECT_SCHEMA

        migrated = migrate_project(source)

        self.assertEqual(
            migrated["conversion_settings"]["velocity_mode"],
            "preserve",
        )

    def test_current_schema_rejects_unmaterialized_velocity_transform(self) -> None:
        source = _project_payload("layered", 1.0, (0,))
        source["schema_version"] = CURRENT_PROJECT_SCHEMA

        with self.assertRaisesRegex(ValueError, "must already be materialized"):
            migrate_project(source)

    def test_current_schema_rejects_unmaterialized_track_scale(self) -> None:
        source = _project_payload("preserve", 0.75, (0,))
        source["schema_version"] = CURRENT_PROJECT_SCHEMA

        with self.assertRaisesRegex(ValueError, r"tracks\[0\]\.volume_scale"):
            migrate_project(source)

    def test_v10_velocity_modes_bake_to_stable_game_native_golden_data(self) -> None:
        note_types = (0, 1, 99, 0)
        for mode, expected_velocities in _GOLDEN_VELOCITIES_AT_075.items():
            with self.subTest(mode=mode):
                source = _project_payload(mode, 0.75, note_types)
                source_copy = deepcopy(source)

                migrated = migrate_project(source)
                migrated_again = migrate_project(migrated)

                self.assertEqual(source, source_copy)
                self.assertEqual(migrated, migrated_again)
                self.assertEqual(
                    migrated["schema_version"],
                    CURRENT_PROJECT_SCHEMA,
                )
                track = migrated["tracks"][0]
                self.assertEqual(track["volume_scale"], 1.0)
                self.assertEqual(
                    [raw_note[1] for raw_note in track["notes"]],
                    expected_velocities,
                )
                self.assertEqual(
                    [raw_note[4] for raw_note in track["notes"]],
                    list(note_types),
                )
                self.assertEqual(
                    [raw_note[5] for raw_note in track["notes"]],
                    [f"future-column-{index}" for index in range(4)],
                )
                settings = ConversionSettings.from_project_payload(
                    migrated["conversion_settings"]
                )
                self.assertEqual(settings.velocity_mode, "preserve")
                self.assertTrue(settings.is_neutral_export_transform())

    def test_migrated_notes_match_every_legacy_mode_scale_and_ntype_export(self) -> None:
        for mode in _MODE_PARAMETERS:
            # The historical exporter rejected non-layered values that scaled
            # above 127 instead of saturating them.  This equivalence matrix
            # therefore covers the complete domain that produced an export;
            # the migration golden above owns the new bounded note data.
            for scale in (0.5, 0.75, 1.0):
                for note_type in (0, 1, 99):
                    with self.subTest(
                        mode=mode,
                        scale=scale,
                        note_type=note_type,
                    ):
                        source = _project_payload(
                            mode,
                            scale,
                            (note_type,),
                        )
                        original_notes = _notes_from_project(source)
                        expected = _legacy_export(
                            original_notes,
                            mode=mode,
                            scale=scale,
                        )

                        migrated = migrate_project(source)
                        actual = _game_native_export(
                            _notes_from_project(migrated)
                        )

                        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
