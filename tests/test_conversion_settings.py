from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from bdo_music_composer.core.conversion_settings import (
    ConversionSettings,
    DEFAULT_CONVERSION_TRANSPOSE,
    LEGACY_CONVERSION_TRANSPOSE,
)


class ConversionSettingsTests(unittest.TestCase):
    def test_all_default_entry_paths_are_game_native_and_neutral(self) -> None:
        self.assertEqual(DEFAULT_CONVERSION_TRANSPOSE, 0)
        self.assertEqual(LEGACY_CONVERSION_TRANSPOSE, 0)

        entry_paths = {
            "new score": ConversionSettings.new_score_defaults(),
            "empty preferences": ConversionSettings.from_preferences({}),
            "legacy MIDI": ConversionSettings.legacy_project_defaults("midi"),
            "legacy BDO": ConversionSettings.bdo_import_defaults(),
            "missing MIDI project fields": ConversionSettings.from_project_payload(
                {}, source_format="midi"
            ),
            "missing BDO project fields": ConversionSettings.from_project_payload(
                {}, source_format="bdo"
            ),
        }
        for entry_path, settings in entry_paths.items():
            with self.subTest(entry_path=entry_path):
                self.assertIsNone(settings.bpm_override)
                self.assertEqual(settings.transpose, 0)
                self.assertEqual(settings.velocity_mode, "preserve")
                self.assertTrue(settings.is_neutral_export_transform())

    def test_preferences_overlay_defaults_and_normalize_json_pairs(self) -> None:
        settings = ConversionSettings.from_preferences(
            {
                "bpm_override": 150,
                "transpose": -12,
                "apply_sustain": False,
                "flatten_tempo": True,
                "velocity_mode": "stepped",
                "vel_floor": 32,
                "vel_step": [32, 9],
            }
        )
        self.assertEqual(settings.bpm_override, 150)
        self.assertEqual(settings.transpose, -12)
        self.assertFalse(settings.apply_sustain)
        self.assertTrue(settings.flatten_tempo)
        self.assertEqual(settings.vel_step, (32, 9))
        self.assertEqual(
            ConversionSettings.from_preferences(settings.to_payload()),
            settings,
        )

    def test_falsey_velocity_mode_cannot_reactivate_legacy_layering(self) -> None:
        for value in (None, ""):
            with self.subTest(value=value):
                settings = ConversionSettings(
                    velocity_mode=value  # type: ignore[arg-type]
                )
                self.assertEqual(settings.velocity_mode, "preserve")
                self.assertTrue(settings.is_neutral_export_transform())

    def test_project_overlay_never_inherits_an_unrelated_open_score(self) -> None:
        legacy = ConversionSettings.from_project_payload(
            {"char_name": "ignored by transform model"},
            source_format="midi",
        )
        self.assertIsNone(legacy.bpm_override)
        self.assertEqual(legacy.transpose, 0)
        self.assertEqual(legacy.velocity_mode, "preserve")

        imported = ConversionSettings.from_project_payload(
            {},
            source_format="bdo",
        )
        self.assertEqual(imported.transpose, 0)
        self.assertEqual(imported.velocity_mode, "preserve")

    def test_export_projection_activates_only_the_selected_velocity_policy(self) -> None:
        settings = ConversionSettings(
            bpm_override=132,
            transpose=-8,
            velocity_mode="rescale",
            vel_range=(28, 112),
            vel_floor=40,
            vel_step=(40, 10),
        )
        params = settings.export_transform_parameters()
        self.assertEqual(params["vel_range"], (28, 112))
        self.assertIsNone(params["vel_floor"])
        self.assertIsNone(params["vel_step"])
        self.assertFalse(params["vel_layered"])
        self.assertFalse(settings.is_neutral_export_transform())

        neutral = ConversionSettings.bdo_import_defaults()
        self.assertTrue(neutral.is_neutral_export_transform())
        self.assertEqual(
            neutral.export_transform_parameters(),
            {
                "bpm_override": None,
                "vel_range": None,
                "vel_floor": None,
                "vel_step": None,
                "vel_layered": False,
                "transpose": 0,
            },
        )

    def test_midi_parse_projection_exposes_only_parser_owned_fields(self) -> None:
        settings = ConversionSettings(
            apply_sustain=False,
            flatten_tempo=True,
            bpm_override=132,
            transpose=-8,
        )
        self.assertEqual(
            settings.midi_parse_parameters(),
            {
                "apply_sustain": False,
                "flatten_tempo": True,
            },
        )

    def test_typed_export_boundary_takes_priority_over_legacy_flat_fields(self) -> None:
        typed = ConversionSettings(
            bpm_override=None,
            transpose=-8,
            velocity_mode="layered",
        )
        restored = ConversionSettings.from_export_parameters(
            {
                "conversion_settings": typed,
                "bpm_override": 200,
                "transpose": 24,
                "vel_layered": False,
            }
        )
        self.assertIs(restored, typed)

    def test_nested_export_mapping_is_parsed_without_silent_fallback(self) -> None:
        restored = ConversionSettings.from_export_parameters(
            {
                "conversion_settings": {
                    "transpose": -12,
                    "velocity_mode": "layered",
                },
                "transpose": 24,
                "vel_layered": False,
            }
        )

        self.assertEqual(restored.transpose, -12)
        self.assertEqual(restored.velocity_mode, "layered")
        with self.assertRaisesRegex(ValueError, "unsupported velocity mode"):
            ConversionSettings.from_export_parameters(
                {"conversion_settings": {"velocity_mode": "layerd"}}
            )
        with self.assertRaisesRegex(TypeError, "must be"):
            ConversionSettings.from_export_parameters(
                {"conversion_settings": ["preserve"]}
            )

    def test_settings_are_immutable_but_support_atomic_updates(self) -> None:
        settings = ConversionSettings.new_score_defaults()
        with self.assertRaises(FrozenInstanceError):
            settings.transpose = 0  # type: ignore[misc]
        changed = settings.with_updates(transpose=-12, velocity_mode="off")
        self.assertEqual(settings.transpose, 0)
        self.assertEqual(changed.transpose, -12)
        self.assertEqual(changed.velocity_mode, "off")


if __name__ == "__main__":
    unittest.main()
