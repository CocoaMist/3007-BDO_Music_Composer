from __future__ import annotations

import json
from pathlib import Path
import unittest

from bdo_instrument_samples import (
    MARNIAN_SYNTH_MODES,
    ROW_VOLUME_DB_MAX,
    ROW_VOLUME_DB_MIN,
    WwiseContainerRotation,
    preview_has_native_articulation,
    preview_pitch_offset_semitones,
    preview_route_ntype,
    row_instance_limit,
    row_loop_points,
    row_release_ms,
    row_volume_gain,
    sample_pitch_ratio,
    select_zone_row,
    select_zone_variants,
)
from bdo_midi import MARNIAN_SYNTH_MODE_OFFSETS


ROOT = Path(__file__).resolve().parents[1]
MAPPING_PATH = ROOT / "data" / "mappings" / "bdo_wwise_midi_map.json"


def _row(
    source_id: int,
    *,
    ntype: int,
    group_id: int,
    root_note: int = 60,
) -> dict:
    return {
        "sound_id": source_id + 1000,
        "source_id": source_id,
        "root_note": root_note,
        "key_min": 48,
        "key_max": 72,
        "velocity_min": 0,
        "velocity_max": 127,
        "route_ntypes": [ntype],
        "selection_group_id": group_id,
        "selection_mode": "random",
        "avoid_repeat": 1,
        "wav_exists": True,
    }


class InstrumentSampleSelectionTests(unittest.TestCase):
    def test_marnian_sample_modes_follow_the_wire_mapping(self) -> None:
        self.assertEqual(
            MARNIAN_SYNTH_MODES,
            tuple(MARNIAN_SYNTH_MODE_OFFSETS),
        )

    def test_neutral_percussion_notes_route_to_game_event_99(self) -> None:
        for instrument_id in (0x04, 0x05, 0x0D, 0x13):
            self.assertEqual(
                preview_route_ntype(instrument_id, 0),
                99,
            )
            self.assertEqual(
                preview_route_ntype(instrument_id, 99),
                99,
            )
        self.assertEqual(preview_route_ntype(0x0A, 0), 0)

    @classmethod
    def setUpClass(cls) -> None:
        payload = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
        cls.banks = payload["banks"]

    def test_event_route_is_resolved_before_overlapping_midi_zones(self) -> None:
        rows = [
            _row(20, ntype=13, group_id=200),
            _row(10, ntype=0, group_id=100),
        ]
        self.assertEqual(
            select_zone_row(rows, 60, 100, ntype=0)["source_id"],
            10,
        )
        self.assertEqual(
            select_zone_row(rows, 60, 100, ntype=13)["source_id"],
            20,
        )

    def test_unknown_articulation_falls_back_to_sustain_not_another_route(
        self,
    ) -> None:
        rows = [
            _row(20, ntype=13, group_id=200),
            _row(10, ntype=0, group_id=100),
        ]
        self.assertEqual(
            select_zone_row(rows, 60, 100, ntype=99)["source_id"],
            10,
        )

    def test_container_variants_are_deterministic_and_order_independent(
        self,
    ) -> None:
        rows = [
            _row(12, ntype=0, group_id=100),
            _row(10, ntype=0, group_id=100),
            _row(30, ntype=0, group_id=300, root_note=72),
        ]
        forward = select_zone_variants(rows, 60, 100, ntype=0)
        reverse = select_zone_variants(list(reversed(rows)), 60, 100, ntype=0)
        self.assertEqual([row["source_id"] for row in forward], [10, 12])
        self.assertEqual(
            [row["source_id"] for row in reverse],
            [10, 12],
        )
        self.assertEqual(
            select_zone_row(rows, 60, 100, ntype=0, variant_index=3)[
                "source_id"
            ],
            12,
        )
        rotation = WwiseContainerRotation()
        self.assertEqual(
            [
                rotation.choose("bank", forward)["source_id"]
                for _ in range(4)
            ],
            [10, 12, 10, 12],
        )

    def test_container_variants_follow_playlist_then_source_and_sound(
        self,
    ) -> None:
        first = _row(30, ntype=0, group_id=100)
        first.update({"playlist_index": 2, "sound_id": 900})
        second = _row(10, ntype=0, group_id=100)
        second.update({"playlist_index": 1, "sound_id": 800})
        repeated_source = _row(10, ntype=0, group_id=100)
        repeated_source.update({"playlist_index": 3, "sound_id": 700})

        variants = select_zone_variants(
            [repeated_source, first, second],
            60,
            100,
            ntype=0,
        )

        self.assertEqual(
            [
                (row["playlist_index"], row["source_id"], row["sound_id"])
                for row in variants
            ],
            [(1, 10, 800), (2, 30, 900), (3, 10, 700)],
        )

    def test_checked_in_distortion_bank_separates_sustain_and_mute(
        self,
    ) -> None:
        rows = self.banks[
            "midi_instrument_26_proguitarelectricdist"
        ]
        sustain = select_zone_variants(rows, 36, 100, ntype=0)
        mute = select_zone_variants(rows, 36, 100, ntype=13)
        self.assertEqual(
            {tuple(row["route_ntypes"]) for row in sustain},
            {(0,)},
        )
        self.assertEqual(
            {tuple(row["route_ntypes"]) for row in mute},
            {(13,)},
        )
        self.assertTrue(
            {row["source_id"] for row in sustain}.isdisjoint(
                row["source_id"] for row in mute
            )
        )
        self.assertEqual(
            {row["route_event_ids"][0] for row in sustain},
            {4264635765},
        )
        self.assertEqual(
            {row["route_event_ids"][0] for row in mute},
            {4247858049},
        )

    def test_game_authored_low_velocity_drum_transposition_is_preserved(
        self,
    ) -> None:
        rows = self.banks["midi_instrument_13_prodrumset"]
        low = select_zone_row(rows, 52, 90, ntype=99)
        high = select_zone_row(rows, 52, 110, ntype=99)
        self.assertEqual(low["source_id"], 339091624)
        self.assertEqual(low["root_note"], 12)
        self.assertEqual(high["root_note"], 48)

    def test_native_harmonic_route_is_not_shifted_a_second_time(self) -> None:
        self.assertEqual(
            preview_pitch_offset_semitones(14, native_articulation=True),
            0,
        )
        self.assertEqual(
            preview_pitch_offset_semitones(14, native_articulation=False),
            12,
        )

    def test_marnian_sample_route_does_not_claim_unrecovered_parent_dsp(
        self,
    ) -> None:
        row = {"route_ntypes": [26]}
        self.assertTrue(
            preview_has_native_articulation(0x0A, row, 26)
        )
        self.assertFalse(
            preview_has_native_articulation(0x14, row, 26)
        )
        self.assertFalse(
            preview_has_native_articulation(0x0A, row, 13)
        )

    def test_static_game_pitch_is_included_in_playback_ratio(self) -> None:
        row = {
            "root_note": 60,
            "pitch_cents": 20.0,
            "pitch_random_min_cents": -50.0,
            "pitch_random_max_cents": 50.0,
        }
        self.assertAlmostEqual(
            sample_pitch_ratio(row, 60),
            2.0 ** (20.0 / 1_200.0),
        )

    def test_row_volume_gain_is_finite_bounded_and_defaults_to_unity(
        self,
    ) -> None:
        self.assertEqual(row_volume_gain({}), 1.0)
        self.assertAlmostEqual(
            row_volume_gain({"volume_db": -6.0}),
            10.0 ** (-6.0 / 20.0),
        )
        self.assertEqual(
            row_volume_gain({"volume_db": float("nan")}),
            1.0,
        )
        self.assertEqual(
            row_volume_gain({"volume_db": float("inf")}),
            1.0,
        )
        self.assertAlmostEqual(
            row_volume_gain({"volume_db": -1_000.0}),
            10.0 ** (ROW_VOLUME_DB_MIN / 20.0),
        )
        self.assertAlmostEqual(
            row_volume_gain({"volume_db": 1_000.0}),
            10.0 ** (ROW_VOLUME_DB_MAX / 20.0),
        )

    def test_row_loop_points_are_validated_and_rate_scaled(self) -> None:
        row = {
            "sample_loops": True,
            "loop_start_frame": 480,
            "loop_end_frame": 960,
        }
        self.assertEqual(
            row_loop_points(
                row,
                720,
                source_sample_rate=48_000,
                output_sample_rate=36_000,
            ),
            (360, 720),
        )
        self.assertEqual(
            row_loop_points(
                {"sample_loops": True},
                720,
                source_sample_rate=48_000,
                output_sample_rate=36_000,
            ),
            (0, 720),
        )
        self.assertEqual(
            row_loop_points(
                {
                    "sample_loops": 2,
                    "sample_loop_regions": [
                        {"start_frame": 10, "end_frame": 40},
                        {"start_frame": 50, "end_frame": 90},
                    ],
                },
                100,
            ),
            (10, 40),
        )
        self.assertIsNone(
            row_loop_points(
                {
                    "sample_loops": True,
                    "loop_start_frame": 20,
                    "loop_end_frame": 20,
                },
                100,
            )
        )
        self.assertIsNone(row_loop_points({}, 100))

    def test_row_release_is_bounded_and_invalid_values_are_safe(self) -> None:
        self.assertIsNone(row_release_ms({}))
        self.assertEqual(row_release_ms({"release_ms": 25}), 25.0)
        self.assertEqual(row_release_ms({"release_ms": -1}), 0.0)
        self.assertIsNone(row_release_ms({"release_ms": "invalid"}))

    def test_row_instance_limit_prefers_scalar_lineage_and_keeps_scope(self) -> None:
        policy = row_instance_limit({
            "instance_group_id": 77,
            "max_instances": 3,
            "kill_newest": True,
            "instance_limit_global": False,
            "instance_use_virtual_behavior": False,
        })
        self.assertTrue(policy.enforceable)
        self.assertEqual(policy.group_id, 77)
        self.assertEqual(policy.max_instances, 3)
        self.assertTrue(policy.kill_newest)
        self.assertFalse(policy.global_scope)

        ambiguous = row_instance_limit({
            "instance_group_id": None,
            "max_instances": 0,
            "selection_group_id": 88,
            "selection_max_instances": 5,
        })
        self.assertFalse(ambiguous.enforceable)
        virtual = row_instance_limit({
            "instance_group_id": 99,
            "max_instances": 1,
            "instance_use_virtual_behavior": True,
        })
        self.assertFalse(virtual.enforceable)
        legacy = row_instance_limit({
            "selection_group_id": 55,
            "selection_max_instances": 2,
            "selection_kill_newest": "true",
            "selection_global": True,
        })
        self.assertTrue(legacy.enforceable)
        self.assertEqual(legacy.group_id, 55)
        self.assertEqual(legacy.max_instances, 2)
        self.assertTrue(legacy.kill_newest)
        self.assertTrue(legacy.global_scope)

    def test_checked_in_map_has_eight_per_object_runtime_limit_groups(self) -> None:
        policies = {
            policy
            for rows in self.banks.values()
            for row in rows
            if (policy := row_instance_limit(row)).max_instances > 0
        }
        self.assertEqual(len(policies), 8)
        self.assertEqual(
            {policy.max_instances for policy in policies},
            {1, 3, 5},
        )
        self.assertTrue(all(policy.enforceable for policy in policies))
        self.assertTrue(all(not policy.global_scope for policy in policies))
        self.assertTrue(all(not policy.kill_newest for policy in policies))


if __name__ == "__main__":
    unittest.main()
