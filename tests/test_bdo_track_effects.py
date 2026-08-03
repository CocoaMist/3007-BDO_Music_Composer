from __future__ import annotations

import math
import unittest

from bdo_common.bdo_track_effects import (
    DEFAULT_TRACK_VOLUME,
    MasterEffects,
    TrackEffectSends,
    decode_track_effects,
    encode_track_effects,
    game_percent,
    raw_track_settings,
    track_volume_preview_gain,
)


class BdoTrackEffectSemanticsTests(unittest.TestCase):
    def test_decodes_verified_track_and_master_layers(self) -> None:
        sends, master = decode_track_effects((11, 22, 33, 44, 55, 66, 77, 88))
        self.assertEqual(sends, TrackEffectSends(11, 33, 55))
        self.assertEqual(master, MasterEffects(22, 44, 66, 77, 88))

    def test_encoding_one_layer_preserves_the_other_bytes(self) -> None:
        original = (1, 2, 3, 4, 5, 6, 7, 8)
        with_sends = encode_track_effects(
            original,
            sends=TrackEffectSends.authored(10, 20, 30),
        )
        self.assertEqual(with_sends, (10, 2, 20, 4, 30, 6, 7, 8))
        with_master = encode_track_effects(
            original,
            master=MasterEffects.authored(12, 34, 56, 78, 90),
        )
        self.assertEqual(with_master, (1, 12, 3, 34, 5, 56, 78, 90))

    def test_game_authoring_range_is_zero_to_one_hundred(self) -> None:
        self.assertEqual(game_percent(0, "value"), 0)
        self.assertEqual(game_percent(100, "value"), 100)
        with self.assertRaises(ValueError):
            game_percent(101, "value")
        with self.assertRaises(ValueError):
            TrackEffectSends.authored(-1, 0, 0)
        with self.assertRaises(ValueError):
            MasterEffects.authored(0, 0, 0, 0, 127)

    def test_raw_lossless_boundary_keeps_external_bytes(self) -> None:
        self.assertEqual(
            raw_track_settings((0, 255, 0, 254, 0, 253, 252, 251)),
            (0, 255, 0, 254, 0, 253, 252, 251),
        )
        with self.assertRaises(ValueError):
            raw_track_settings((0,) * 7)

    def test_legacy_master_adapter_is_stable(self) -> None:
        master = MasterEffects.from_legacy(40, 20, (10, 30, 50), authored=True)
        self.assertEqual(master.legacy_values(), (40, 20, (10, 30, 50)))
        self.assertEqual(
            MasterEffects.from_legacy(0, 0, None).legacy_values(),
            (0, 0, None),
        )

    def test_preview_gain_is_finite_bounded_and_preserves_game_default(self) -> None:
        self.assertEqual(DEFAULT_TRACK_VOLUME, 70)
        self.assertTrue(math.isclose(track_volume_preview_gain(70), 0.7))
        self.assertEqual(track_volume_preview_gain(0), 0.0)
        self.assertEqual(track_volume_preview_gain(100), 1.0)
        self.assertEqual(track_volume_preview_gain(255), 1.0)
        self.assertTrue(
            math.isclose(
                track_volume_preview_gain(float("nan")),
                DEFAULT_TRACK_VOLUME / 100.0,
            )
        )


if __name__ == "__main__":
    unittest.main()
